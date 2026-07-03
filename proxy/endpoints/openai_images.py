import logging
import time
import uuid

from fastapi import APIRouter, HTTPException

from chatgpt_oauth import ChatGPTOAuthManager
from providers.chatgpt_image_provider import ChatGPTImageProvider
from ..models import OpenAIImageGenerationRequest

logger = logging.getLogger(__name__)
router = APIRouter()

chatgpt_oauth_manager = ChatGPTOAuthManager()


@router.post("/v1/images/generations")
async def openai_image_generations(request: OpenAIImageGenerationRequest):
    request_id = str(uuid.uuid4())[:8]
    logger.info(f"[{request_id}] ===== NEW OPENAI IMAGE GENERATION REQUEST =====")

    request_dict = request.model_dump()
    count = 1 if request.n is None else request.n
    if count < 1:
        raise HTTPException(status_code=400, detail={"error": {"message": "n must be at least 1"}})
    if count > 4:
        raise HTTPException(status_code=400, detail={"error": {"message": "n must be 4 or less"}})

    provider = ChatGPTImageProvider(oauth_manager=chatgpt_oauth_manager)

    try:
        data = []
        for _ in range(count):
            image_b64 = await provider.generate_image_b64(request_dict, request_id)
            if request.response_format == "url":
                data.append({"url": f"data:image/{request.output_format or 'png'};base64,{image_b64}"})
            else:
                data.append({"b64_json": image_b64})
        return {"created": int(time.time()), "data": data}
    except ValueError as e:
        logger.error(f"[{request_id}] ChatGPT image auth/request error: {e}")
        raise HTTPException(status_code=401, detail={"error": {"message": str(e)}})
    except Exception as e:
        logger.error(f"[{request_id}] ChatGPT image generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"error": {"message": f"ChatGPT image generation failed: {str(e)}"}})
