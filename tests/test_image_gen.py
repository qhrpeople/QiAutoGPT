import functools
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from autogpt.commands.image_gen import generate_image, generate_image_with_sd_webui
from tests.utils import requires_api_key


@pytest.fixture(params=[256, 512, 1024])
def image_size(request):
    """Parametrize image size."""
    return request.param


@pytest.mark.xfail(
    reason="The image is too big to be put in a cassette for a CI pipeline. We're looking into a solution."
)
@requires_api_key("OPENAI_API_KEY")
def test_dalle(config, workspace, image_size, patched_api_requestor):
    """Test DALL-E image generation."""
    generate_and_validate(
        config,
        workspace,
        image_provider="dalle",
        image_size=image_size,
    )


@pytest.mark.xfail(
    reason="The image is too big to be put in a cassette for a CI pipeline. We're looking into a solution."
)
@requires_api_key("HUGGINGFACE_API_TOKEN")
@pytest.mark.parametrize(
    "image_model",
    ["CompVis/stable-diffusion-v1-4", "stabilityai/stable-diffusion-2-1"],
)
def test_huggingface(config, workspace, image_size, image_model):
    """Test HuggingFace image generation."""
    generate_and_validate(
        config,
        workspace,
        image_provider="huggingface",
        image_size=image_size,
        hugging_face_image_model=image_model,
    )


@pytest.mark.skip(reason="External SD WebUI may not be available.")
def test_sd_webui(config, workspace, image_size):
    """Test SD WebUI image generation."""
    generate_and_validate(
        config,
        workspace,
        image_provider="sdwebui",
        image_size=image_size,
    )


@pytest.mark.skip(reason="External SD WebUI may not be available.")
def test_sd_webui_negative_prompt(config, workspace, image_size):
    gen_image = functools.partial(
        generate_image_with_sd_webui,
        prompt="astronaut riding a horse",
        size=image_size,
        extra={"seed": 123},
    )

    # Generate an image with a negative prompt
    image_path = lst(gen_image(negative_prompt="horse", filename="negative.jpg"))
    with Image.open(image_path) as img:
        neg_image_hash = hashlib.md5(img.tobytes()).hexdigest()

    # Generate an image without a negative prompt
    image_path = lst(gen_image(filename="positive.jpg"))
    with Image.open(image_path) as img:
        image_hash = hashlib.md5(img.tobytes()).hexdigest()

    assert image_hash != neg_image_hash

def lst(txt):
    """Extract the file path from the output of `generate_image()`"""
    return Path(txt.split(":", maxsplit=1)[1].strip())


def generate_and_validate(
    config,
    workspace,
    image_size,
    image_provider,
    hugging_face_image_model=None,
    **kwargs,
):
    """Generate an image and validate the output."""
    config.image_provider = image_provider
    config.huggingface_image_model = hugging_face_image_model
    prompt = "astronaut riding a horse"

    image_path = lst(generate_image(prompt, image_size, **kwargs))
    assert image_path.exists()
    with Image.open(image_path) as img:
        assert img.size == (image_size, image_size)
        
        
# @requires_api_key("HUGGINGFACE_API_TOKEN")
@pytest.mark.parametrize(
    "return_text",
    [
        '{"error":"Model [model] is currently loading","estimated_time": [delay]}', # Delay
        '{"error":"Model [model] is currently loading"}',# No delay
        '{"error:}', # Bad JSON
        '', # Bad Image
        ]
)
@pytest.mark.parametrize(
    "image_model",
    ["CompVis/stable-diffusion-v1-4", "stabilityai/stable-diffusion-2-1"],
)
@pytest.mark.parametrize("delay", [10, 0])
def test_huggingface_fail_request_with_delay(config, workspace, image_size, image_model, return_text, delay):
    config.huggingface_api_token = "1"
    
    return_text = return_text.replace('[model]', image_model).replace('[delay]', str(delay))
        
    with(patch("requests.post")) as mock_post:
        if return_text == '':
            # Test bad image
            mock_post.return_value.status_code = 200
            mock_post.return_value.ok = True
            mock_post.return_value.content = b'bad image'
        else:
            # Test delay and bad json
            mock_post.return_value.status_code = 500
            mock_post.return_value.ok = False
            mock_post.return_value.text = return_text
            
        config.image_provider = "huggingface"
        config.huggingface_image_model = image_model
        prompt = "astronaut riding a horse"
        
        with(patch("time.sleep")) as mock_sleep:
            # Verify request fails.                                                                                                                                                                                                              
            result = generate_image(prompt, image_size)
            assert result == "Error creating image."

            # Verify retry was called with delay if delay is in return_text
            if "estimated_time" in return_text:
                mock_sleep.assert_called_with(delay)
            else:
                mock_sleep.assert_not_called()