"""Синхронная обработка изображений через Pillow."""

import warnings
from io import BytesIO
from typing import Optional

from PIL import Image, ImageOps

from app.models.images import ProcessedImage


class ImageProcessor:
    """Конвертирует и сжимает изображения в JPEG."""

    def __init__(
        self,
        max_image_dimension: int = 10_000,
        max_image_pixels: int = 40_000_000,
    ) -> None:
        """Сохраняет ограничения декодирования изображения."""
        if max_image_dimension <= 0 or max_image_pixels <= 0:
            raise ValueError(
                "Ограничения изображения должны быть положительными"
            )
        self._max_image_dimension = max_image_dimension
        self._max_image_pixels = max_image_pixels

    def convert_to_jpeg(
        self,
        content: bytes,
        quality: Optional[int],
        target_width: Optional[int],
        target_height: Optional[int],
    ) -> ProcessedImage:
        """Создаёт JPEG с запрошенными параметрами."""
        with warnings.catch_warnings():
            warnings.simplefilter(
                "error",
                Image.DecompressionBombWarning,
            )
            with Image.open(BytesIO(content)) as source:
                self._validate_dimensions(source.width, source.height)
                source.load()
                needs_processing = (
                    source.format != "JPEG"
                    or quality is not None
                    or target_width is not None
                    or target_height is not None
                )
                if not needs_processing:
                    return ProcessedImage(
                        content=content,
                        width=source.width,
                        height=source.height,
                        size_bytes=len(content),
                        quality=None,
                    )

                image = ImageOps.exif_transpose(source)
                image = self._resize(
                    image,
                    target_width=target_width,
                    target_height=target_height,
                )
                image = self._convert_to_rgb(image)

                output = BytesIO()
                save_options = {}
                if quality is not None:
                    save_options["quality"] = quality

                image.save(
                    output,
                    format="JPEG",
                    **save_options,
                )
                result = output.getvalue()

        return ProcessedImage(
            content=result,
            width=image.width,
            height=image.height,
            size_bytes=len(result),
            quality=quality,
        )

    def _resize(
        self,
        image: Image.Image,
        target_width: Optional[int],
        target_height: Optional[int],
    ) -> Image.Image:
        """Изменяет только переданные размеры изображения."""
        size = (
            target_width or image.width,
            target_height or image.height,
        )
        self._validate_dimensions(*size)
        if size == image.size:
            return image
        return image.resize(size, Image.Resampling.LANCZOS)

    def _validate_dimensions(self, width: int, height: int) -> None:
        """Проверяет стороны и число пикселей изображения."""
        if (
            width > self._max_image_dimension
            or height > self._max_image_dimension
        ):
            raise ValueError(
                "Размер стороны изображения превышает допустимый предел"
            )
        if width * height > self._max_image_pixels:
            raise ValueError(
                "Число пикселей изображения превышает допустимый предел"
            )

    @staticmethod
    def _convert_to_rgb(image: Image.Image) -> Image.Image:
        """Подготавливает цветовой режим для сохранения JPEG."""
        has_transparency = (
            "A" in image.getbands()
            or "transparency" in image.info
        )
        if not has_transparency:
            return image.convert("RGB")

        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
