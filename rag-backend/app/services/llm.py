"""LLM service for RAG generation using OpenAI or Azure OpenAI"""

from typing import List, Dict, Any, Optional
import openai
from openai import AsyncOpenAI, AsyncAzureOpenAI
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


class LLMService:
    """LLM service for generating responses with retrieved context"""

    def __init__(self):
        self.client: AsyncOpenAI | AsyncAzureOpenAI | None = None

    async def initialize(self):
        """Initialize OpenAI or Azure OpenAI client"""
        try:
            if settings.use_azure_openai:
                self.client = AsyncAzureOpenAI(
                    api_key=settings.azure_openai_api_key,
                    api_version=settings.azure_openai_api_version,
                    azure_endpoint=settings.azure_openai_endpoint
                )
                logger.info("Initialized Azure OpenAI client")
            else:
                self.client = AsyncOpenAI(api_key=settings.openai_api_key)
                logger.info("Initialized OpenAI client")

        except Exception as e:
            logger.error("Failed to initialize LLM client", error=str(e))
            raise

    async def generate_answer(
        self,
        question: str,
        context_chunks: List[Dict[str, Any]],
        equipment_model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate answer using RAG context

        Args:
            question: User's question
            context_chunks: Retrieved context chunks
            equipment_model: Optional equipment model filter
            temperature: LLM temperature
            max_tokens: Max response tokens
            system_prompt: Optional custom system prompt

        Returns:
            Generated answer with metadata
        """
        if self.client is None:
            raise RuntimeError("LLM client not initialized")

        try:
            context_text = self._build_context(context_chunks)

            if system_prompt is None:
                system_prompt = self._get_default_system_prompt(equipment_model)

            user_prompt = self._build_user_prompt(question, context_text)

            model_name = settings.openai_model
            if settings.use_azure_openai:
                model_name = settings.azure_openai_deployment_name

            response = await self.client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )

            answer = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason

            confidence = self._calculate_confidence(context_chunks, finish_reason)

            result = {
                "answer": answer,
                "confidence": confidence,
                "finish_reason": finish_reason,
                "model": model_name,
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }

            logger.info(
                "Generated answer",
                question_length=len(question),
                context_chunks=len(context_chunks),
                answer_length=len(answer),
                total_tokens=result["total_tokens"]
            )

            return result

        except Exception as e:
            logger.error("Failed to generate answer", error=str(e))
            raise

    async def generate_with_vision(
        self,
        question: str,
        image_base64: str,
        context_chunks: List[Dict[str, Any]],
        equipment_model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> Dict[str, Any]:
        """
        Generate answer with vision capabilities (for image-based queries)

        Args:
            question: User's question
            image_base64: Base64 encoded image
            context_chunks: Retrieved context chunks
            equipment_model: Optional equipment model
            temperature: LLM temperature
            max_tokens: Max response tokens

        Returns:
            Generated answer with status
        """
        if self.client is None:
            raise RuntimeError("LLM client not initialized")

        try:
            context_text = self._build_context(context_chunks)

            system_prompt = self._get_vision_system_prompt(equipment_model)
            user_prompt = self._build_vision_user_prompt(question, context_text)

            model_name = "gpt-4-vision-preview"
            if settings.use_azure_openai:
                model_name = "gpt-4-vision"

            response = await self.client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )

            answer = response.choices[0].message.content

            parsed = self._parse_vision_response(answer)

            result = {
                **parsed,
                "model": model_name,
                "total_tokens": response.usage.total_tokens
            }

            logger.info(
                "Generated vision answer",
                status=parsed.get("status"),
                total_tokens=result["total_tokens"]
            )

            return result

        except Exception as e:
            logger.error("Failed to generate vision answer", error=str(e))
            raise

    def _build_context(self, chunks: List[Dict[str, Any]]) -> str:
        """Build context string from chunks"""
        context_parts = []

        for i, chunk in enumerate(chunks, 1):
            doc_title = chunk.get("document_title", "Unknown Document")
            page = chunk.get("page_number", 0)
            content = chunk.get("content", "")

            if page > 0:
                source = f"[{doc_title}, Page {page}]"
            else:
                source = f"[{doc_title}]"

            context_parts.append(f"{i}. {source}\n{content}\n")

        return "\n".join(context_parts)

    def _get_default_system_prompt(self, equipment_model: Optional[str] = None) -> str:
        """Get default system prompt for RAG"""
        base_prompt = """You are an AI assistant helping operators with equipment deployment and troubleshooting.

Your role is to provide accurate, concise, and helpful answers based on the provided documentation context.

Guidelines:
- Answer questions accurately using the provided context
- If the context doesn't contain enough information, say so clearly
- Be concise but thorough
- Use technical terminology when appropriate
- Always cite sources when referencing specific procedures
- Prioritize safety and correct procedures"""

        if equipment_model:
            base_prompt += f"\n- You are specifically helping with {equipment_model}"

        return base_prompt

    def _build_user_prompt(self, question: str, context: str) -> str:
        """Build user prompt with question and context"""
        return f"""Based on the following documentation context, please answer the question.

Context:
{context}

Question: {question}

Answer:"""

    def _get_vision_system_prompt(self, equipment_model: Optional[str] = None) -> str:
        """Get system prompt for vision-based queries"""
        prompt = """You are an AI assistant analyzing equipment deployment photos.

Analyze the image and respond in the following JSON format:
{{
    "status": "correct" | "needs_adjustment" | "incorrect" | "unclear",
    "voice_instruction": "Brief instruction (max 25 words)",
    "reasoning": "Detailed explanation",
    "advance_step": true | false,
    "safety_concern": true | false,
    "safety_detail": "Details if safety_concern is true"
}}

Use the provided documentation context to inform your analysis."""

        if equipment_model:
            prompt += f"\nYou are analyzing {equipment_model} deployment."

        return prompt

    def _build_vision_user_prompt(self, question: str, context: str) -> str:
        """Build user prompt for vision queries"""
        return f"""Documentation context:
{context}

Task: {question}

Analyze the image and provide your assessment."""

    def _parse_vision_response(self, response: str) -> Dict[str, Any]:
        """Parse vision response (expecting JSON)"""
        try:
            import json
            return json.loads(response)
        except json.JSONDecodeError:
            # Fallback if not JSON
            return {
                "status": "unclear",
                "voice_instruction": response[:100],
                "reasoning": response,
                "advance_step": False,
                "safety_concern": False
            }

    def _calculate_confidence(
        self,
        context_chunks: List[Dict[str, Any]],
        finish_reason: str
    ) -> float:
        """Calculate confidence score based on context quality"""
        if not context_chunks:
            return 0.3

        if finish_reason != "stop":
            return 0.5

        avg_score = sum(chunk.get("score", 0.5) for chunk in context_chunks[:3]) / min(3, len(context_chunks))
        confidence = min(avg_score, 1.0)

        return round(confidence, 2)


# Global instance
llm_service = LLMService()
