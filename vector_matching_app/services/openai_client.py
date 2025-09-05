"""
OpenAI client service voor embeddings en chat functionaliteit.
"""
import openai
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class OpenAIClient:
    """OpenAI client voor embeddings en chat."""
    
    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is niet geconfigureerd")
        
        # Maak client aan met minimale parameters
        self.client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    
    def embed(self, text: str, model: str = "text-embedding-3-small") -> list[float]:
        """
        Haalt embedding op voor de gegeven tekst.
        
        Args:
            text: De tekst om te embedden
            model: Het embedding model om te gebruiken
            
        Returns:
            List van floats die de embedding representeren
            
        Raises:
            Exception: Als de API call faalt
        """
        try:
            response = self.client.embeddings.create(
                input=text,
                model=model
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Fout bij het ophalen van embedding: {e}")
            raise
    
    def chat(self, messages: list[dict], model: str = "gpt-3.5-turbo") -> str:
        """
        Chat functionaliteit met OpenAI.
        
        Args:
            messages: List van message dicts met 'role' en 'content'
            model: Het chat model om te gebruiken
            
        Returns:
            De response van de chat
            
        Raises:
            Exception: Als de API call faalt
        """
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=1000,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Fout bij chat API call: {e}")
            raise


# Singleton instance
_openai_client = None


def get_openai_client() -> OpenAIClient:
    """Haalt de singleton OpenAI client op."""
    global _openai_client
    # Reset client bij elke call om oude instanties te vermijden
    _openai_client = OpenAIClient()
    return _openai_client
