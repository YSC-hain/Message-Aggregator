import logging
import json
import os
from typing import List, Dict, Any, Optional
import base64
import requests
import time
import random
from PIL import Image

class LLMAnalyzer:
    def __init__(
        self, 
        api_key: str, 
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4-vision-preview",
        max_tokens: int = 1000
    ):
        """
        Initialize the LLM Analyzer.
        
        Args:
            api_key: API key for the LLM service
            base_url: Base URL for the API (default OpenAI, change for proxies or other providers)
            model: LLM model to use
            max_tokens: Maximum tokens for response
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.max_tokens = max_tokens
        self.logger = logging.getLogger(__name__)
        
    def _encode_image(self, image_path: str) -> Optional[str]:
        """
        Encode an image to base64.
        
        Args:
            image_path: Path to the image
            
        Returns:
            Base64 encoded image or None if failed
        """
        try:
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            self.logger.error(f"Error encoding image {image_path}: {str(e)}")
            return None
            
    def _resize_image_if_needed(self, image_path: str, max_size: int = 4000000) -> str:
        """
        Resize an image if it exceeds the maximum size.
        
        Args:
            image_path: Path to the image
            max_size: Maximum file size in bytes
            
        Returns:
            Path to the resized image (or original if not resized)
        """
        try:
            file_size = os.path.getsize(image_path)
            
            if file_size <= max_size:
                return image_path
                
            # Check if this image has already been resized
            resized_path = f"{image_path}_resized.jpg"
            if os.path.exists(resized_path):
                if os.path.getsize(resized_path) <= max_size:
                    return resized_path
            
            # Resize the image with PIL
            from PIL import Image
            import io
            
            # Open the image and get its dimensions
            img = Image.open(image_path)
            width, height = img.size
            
            # Calculate scaling factor based on target file size
            scale_factor = (max_size / file_size) ** 0.5
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            
            # Resize the image
            resized_img = img.resize((new_width, new_height), Image.LANCZOS)
            
            # Save with progressively lower quality until size requirement is met
            quality = 85
            while quality >= 60:  # Don't go below quality 60
                resized_path = f"{image_path}_resized.jpg"
                resized_img.save(resized_path, "JPEG", quality=quality)
                
                new_size = os.path.getsize(resized_path)
                if new_size <= max_size:
                    break
                    
                quality -= 10
                
            self.logger.info(f"Resized image from {file_size} to {os.path.getsize(resized_path)} bytes (quality: {quality})")
            return resized_path
            
        except Exception as e:
            self.logger.error(f"Error resizing image {image_path}: {str(e)}")
            return image_path  # Return original if resize failed
    
    def _call_api_with_retry(self, url, headers, payload, max_retries=3, base_delay=2):
        """Make API call with exponential backoff retry logic."""
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=60)
                
                # Handle rate limits (status code 429)
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', base_delay * (2 ** attempt)))
                    self.logger.warning(f"Rate limited. Retrying after {retry_after} seconds.")
                    time.sleep(retry_after)
                    continue
                    
                # Return successful response
                if response.status_code == 200:
                    return response
                    
                # Handle other errors
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    self.logger.warning(f"API request failed with status {response.status_code}. Retrying after {delay:.2f} seconds.")
                    time.sleep(delay)
                else:
                    self.logger.error(f"API request failed after {max_retries} attempts. Status: {response.status_code}, Response: {response.text}")
                    return response
                    
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    self.logger.warning(f"Connection error: {str(e)}. Retrying after {delay:.2f} seconds.")
                    time.sleep(delay)
                else:
                    self.logger.error(f"Connection failed after {max_retries} attempts: {str(e)}")
                    raise
        
        # If we get here, all retries failed
        raise Exception(f"API request failed after {max_retries} attempts")

    def analyze_messages(
        self, 
        messages: List[Dict[str, Any]], 
        channel_descriptions: Dict[str, str] = None,
        analysis_prompt: str = None
    ) -> Dict[str, Any]:
        """
        Analyze messages using the LLM API.
        
        Args:
            messages: List of message dictionaries
            channel_descriptions: Optional dictionary mapping channel_id to description
            analysis_prompt: Custom prompt for analysis
            
        Returns:
            Dictionary containing analysis results
        """
        if not messages:
            return {"summary": "No messages to analyze", "key_points": []}
            
        # Prepare message content
        content = []
        
        # Add system message
        content.append({
            "type": "text",
            "text": ""
        })
        
        # Add context about channels
        if channel_descriptions:
            channel_context = "Channel Information:\n"
            for channel_id, description in channel_descriptions.items():
                channel_context += f"- Channel ID {channel_id}: {description}\n"
            
            content.append({
                "type": "text",
                "text": channel_context
            })
        
        # Add messages
        for msg in messages:
            message_text = f"Channel: {msg.get('channel_title', 'Unknown')}\n"
            message_text += f"Date: {msg.get('date', 'Unknown')}\n"
            message_text += f"Message: {msg.get('text', '')}"
            
            content.append({
                "type": "text",
                "text": message_text
            })
            
            # Add image if available
            if msg.get('media_path') and msg.get('media_type') == 'photo':
                try:
                    # Resize image if needed to meet API requirements
                    resized_image_path = self._resize_image_if_needed(msg['media_path'])
                    encoded_image = self._encode_image(resized_image_path)
                    
                    if encoded_image:
                        content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{encoded_image}"
                            }
                        })
                except Exception as e:
                    self.logger.error(f"Error processing image: {str(e)}")
        
        # Make API request
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            # Prepare default prompt if none provided
            if analysis_prompt is None:
                analysis_prompt = (
                    "Analyze the above messages from different Telegram channels."
                    "Please provide a summary, extracting valuable information, trends, and insights."
                    "Include the most important of these, taking into account the context and focus of each channel."
                    "In \"summary\" is the core summary of all the content of all the channel, and needs to reflect the most important information. In \"content\", you need to output the content according to the type of message, such as \"I. --- Natural Disasters ---\" and \"II. --- Geopolitics & International Relations ---\""
                    "Reply in Cheinese."
                    #"After your normal analysis, please include a JSON response at the end of your message with the following format: ```json {\"summary\": \"the most important information\", \"content\": [\"First content\", \"Second content\", \"Third content\"]} ```\n"
                    "Note: I want you to extract valuable information, not analyze the topics of individual channels. You don't need to give a comment on these messages in the <summary>. In the summary, you only need to output the important information. Please control the number of messages you output in the summary by selecting only the more important ones to display!\n"
                    "Note: The content should be as complete as possible with the information you previously output, and use markdown formatting."
                    "\n\nResponse format: \n**摘要**\n<summary>\n**内容**\n**<title>**:\n <summary>: <content>"
                    )
            content.append({"type": "text","text": str(analysis_prompt)})
            
            self.logger.info(content)

            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                "max_tokens": self.max_tokens
            }

            '''
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload
            )'''
            response = self._call_api_with_retry(f"{self.base_url}/chat/completions", headers, payload, 10, 120)
            
            if response.status_code == 200:
                result = response.json()
                analysis_text = result["choices"][0]["message"]["content"]
                
                self.logger.info(analysis_text)

                # Parse the analysis text into structured data
                analysis_result = self._parse_analysis(analysis_text)
                return analysis_result
            else:
                self.logger.error(f"API request failed with status {response.status_code}: {response.text}")
                return {"error": f"API request failed: {response.text}"}
                
        except Exception as e:
            self.logger.error(f"Error analyzing messages: {str(e)}")
            return {"error": f"Analysis failed: {str(e)}"}
    
    def _parse_analysis(self, analysis_text: str) -> Dict[str, Any]:
        """
        Parse the analysis text into structured data, with support for JSON output.
        
        Args:
            analysis_text: Raw text from LLM response
            
        Returns:
            Structured analysis result
        """
        result = {"summary": "", "contents": []}
    
        # Split into sections
        sections = analysis_text.split("**")
        
        summary_found = False
        content_found = False
        
        for i, section in enumerate(sections):
            if section.strip() == "摘要" and i+1 < len(sections):
                # Next section is the summary content
                result["summary"] = sections[i+1].strip()
                summary_found = True
            
            if section.strip() == "内容" and i+1 < len(sections):
                # Everything after this is content
                content_found = True
                content_text = "**".join(sections[i+1:])
                
                # Parse content into distinct points
                content_sections = []
                current_section = None
                
                for line in content_text.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Check if line is a section header
                    if line.startswith('**') and line.endswith('**'):
                        current_section = line
                        content_sections.append(current_section)
                    elif line.startswith('* ') or line.startswith('- '):
                        # This is a bullet point, add as is
                        content_sections.append(line)
                    else:
                        # Regular content line
                        content_sections.append(line)
                
                result["contents"] = content_sections
                break
        
        # Fallback if structured parsing failed
        if not summary_found and not content_found:
            self.logger.warning("Failed to parse structured output, using fallback")
            
            # Simple fallback: first paragraph is summary, rest is content
            paragraphs = [p for p in analysis_text.split("\n\n") if p.strip()]
            if paragraphs:
                result["summary"] = paragraphs[0].strip()
                if len(paragraphs) > 1:
                    result["contents"] = paragraphs[1:]
        
        return result


def main():
    """Example usage of the LLMAnalyzer."""
    # Replace with your API key
    api_key = "YOUR_API_KEY"
    
    # Initialize analyzer
    analyzer = LLMAnalyzer(
        api_key=api_key,
        base_url="https://api.openai.com/v1",  # Default OpenAI URL
        model="gpt-4-vision-preview",
        max_tokens=1000
    )
    
    # Load messages from file
    with open("collected_messages.json", "r", encoding="utf-8") as f:
        messages = json.load(f)
    
    # Channel descriptions for context
    channel_descriptions = {
        "channel1": "Technology news and updates",
        "channel2": "Financial market analysis",
        "channel3": "Political commentary and current events"
    }
    
    # Analyze messages
    analysis = analyzer.analyze_messages(
        messages=messages,
        channel_descriptions=channel_descriptions
    ) # TODO 缺失analysis_prompt
    
    # Save analysis
    with open("analysis_results.json", "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    
    print("Analysis completed and saved to analysis_results.json")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()