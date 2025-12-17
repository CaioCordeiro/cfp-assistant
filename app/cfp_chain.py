import os
import time
from typing import Optional

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

try:
    from huggingface_hub.errors import BadRequestError
except Exception:  # pragma: no cover
    BadRequestError = Exception  # type: ignore


class CFP(BaseModel):
    title: str = Field(..., description="Concise, compelling talk title")
    abstract: str = Field(..., description="120-200 word abstract suitable for CFP")
    private_message: str = Field(
        ..., description="Private message to organizers with additional details"
    )
    main_language: str = Field(
        ..., description="Main language of the talk (e.g., English, Spanish, etc.)"
    )
    talk_type: str = Field(
        ..., description="Type of talk (e.g., Workshop, Lecture, Keynote, etc.)"
    )
    intended_audience: str = Field(
        ..., description="Intended audience (e.g., Beginners, Intermediate, Advanced)"
    )
    estimated_duration: str = Field(
        ..., description="Estimated duration (e.g., 30 minutes, 1 hour, etc.)"
    )
    live_coding: str = Field(..., description="Will it have live coding?")
    special_requirements: str = Field(
        ...,
        description="Any special requirements (e.g., AV needs, accessibility considerations, etc.)",
    )


def _llm():
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    temperature = float(
        os.environ.get("OPENAI_TEMPERATURE", os.environ.get("HF_TEMPERATURE", "0.2"))
    )

    if provider in {"hf", "huggingface", "hugging_face"}:
        repo_id = os.environ.get("HUGGINGFACE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
        # Default small instruct model for faster latency on free tier
        endpoint = HuggingFaceEndpoint(
            repo_id=repo_id,
            temperature=temperature,
            max_new_tokens=int(os.environ.get("HF_MAX_NEW_TOKENS", "512")),
            top_p=float(os.environ.get("HF_TOP_P", "0.95")),
            huggingfacehub_api_token=os.environ.get("HUGGINGFACE_API_KEY"),
            timeout=10,
        )
        return ChatHuggingFace(llm=endpoint)

    # Default to OpenAI
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    return ChatOpenAI(model=model, temperature=temperature, timeout=10)


def build_cfp_chain():
    parser = PydanticOutputParser(pydantic_object=CFP)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are an expert conference CFP editor. You turn speaker ideas into a great title and abstract. Keep it accurate, inclusive, and free of marketing fluff.",
            ),
            (
                "human",
                """
                Speaker idea:
                {idea}

                Please craft a professional CFP-ready result with:
                - A concise, compelling title
                - A 120-200 word abstract aimed at a technical audience
                - A private message to the organizers telling more about the content of the presentation
                    - What references were used?
                    - How did you get interested in this topic?
                    - Whats the objective of the talk?
                - Main language of the talk (e.g., English, Spanish, etc.)
                - Type of talk (e.g., Workshop, Lecture, Keynote, etc.)
                - Intended audience (e.g., Beginners, Intermediate, Advanced)
                - Estimated duration (e.g., 30 minutes, 1 hour, etc.)
                - Will it have live coding?
                - Any special requirements (e.g., AV needs, accessibility considerations, etc.)
                - No placeholders, emojis, or markdown

                {format_instructions}
                """,
            ),
        ]
    )
    chain = prompt | _llm() | parser
    return chain


def format_cfp(idea: str) -> CFP:
    idea = idea.strip()
    chain = build_cfp_chain()
    parser = PydanticOutputParser(pydantic_object=CFP)

    payload = {
        "idea": idea,
        "format_instructions": parser.get_format_instructions(),
    }

    # One quick retry for HF warmup; keep under 10s total timeout
    for attempt in range(2):
        try:
            return chain.invoke(payload)
        except BadRequestError as e:
            msg = str(e)
            if "model_pending_deploy" in msg and attempt == 0:
                time.sleep(2)
                continue
            break
        except Exception:
            break

    # Fallback: heuristic generator without LLM
    return _fallback_cfp(idea)


def _fallback_cfp(idea: str) -> CFP:
    topic = _extract_topic(idea)
    if len(topic) > 100:
        topic = topic[:57].rstrip() + "..."
    title = f"{topic}: A Practical Introduction"
    abstract = (
        f"This session provides a practical, vendor-neutral introduction to {topic}. We’ll cover the core concepts, common pitfalls, and a concise set of patterns you can apply immediately."
        f" You’ll see how {topic} fits into real-world architectures, what trade‑offs to consider, and how to choose the right approach for your team."
        f" We’ll wrap up with a short demo, example use cases, and a checklist you can take back to your organization. No prior experience with {topic} is required, but familiarity with modern cloud and developer workflows will help."
    )
    private_message = "This fallback abstract was generated without LLM assistance. Please reach out to the speaker for more details about their background and the content of the presentation."
    main_language = "English"
    talk_type = "Lecture"
    intended_audience = "Beginners"
    estimated_duration = "45 minutes"
    live_coding = "No"
    special_requirements = "None"
    return CFP(
        title=title,
        abstract=abstract,
        private_message=private_message,
        main_language=main_language,
        talk_type=talk_type,
        intended_audience=intended_audience,
        estimated_duration=estimated_duration,
        live_coding=live_coding,
        special_requirements=special_requirements,
    )


def _extract_topic(idea: str) -> str:
    lower = idea.lower()
    for marker in ["about ", "on ", "regarding ", "around ", "using "]:
        if marker in lower:
            idx = lower.find(marker) + len(marker)
            return idea[idx:].strip().strip(". ")
    # Fallback: first 8 words
    words = [w.strip(",.;:!?") for w in idea.split() if w.strip()]
    topic = " ".join(words[:8]) if words else "Your Topic"
    return topic.title()
