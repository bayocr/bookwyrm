import colorsys
import math
import os
import textwrap

from colorthief import ColorThief
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageColor
from pathlib import Path
from uuid import uuid4

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.db.models import Avg

from bookwyrm import models, settings
from bookwyrm.settings import DOMAIN
from bookwyrm.tasks import app

IMG_WIDTH = settings.PREVIEW_IMG_WIDTH
IMG_HEIGHT = settings.PREVIEW_IMG_HEIGHT
BG_COLOR = settings.PREVIEW_BG_COLOR
TEXT_COLOR = settings.PREVIEW_TEXT_COLOR
DEFAULT_COVER_COLOR = settings.PREVIEW_DEFAULT_COVER_COLOR
TRANSPARENT_COLOR = (0, 0, 0, 0)

margin = math.floor(IMG_HEIGHT / 10)
gutter = math.floor(margin / 2)
inner_img_height = math.floor(IMG_HEIGHT * 0.8)
inner_img_width = math.floor(inner_img_height * 0.7)
path = Path(__file__).parent.absolute()
font_dir = path.joinpath("static/fonts/public_sans")


def get_font(font_name, size=28):
    if font_name == "light":
        font_path = "%s/PublicSans-Light.ttf" % font_dir
    if font_name == "regular":
        font_path = "%s/PublicSans-Regular.ttf" % font_dir
    elif font_name == "bold":
        font_path = "%s/PublicSans-Bold.ttf" % font_dir

    try:
        font = ImageFont.truetype(font_path, size)
    except OSError:
        font = ImageFont.load_default()

    return font


def generate_texts_layer(texts, content_width):
    font_text_zero = get_font("bold", size=20)
    font_text_one = get_font("bold", size=48)
    font_text_two = get_font("bold", size=40)
    font_text_three = get_font("regular", size=40)

    text_layer = Image.new("RGBA", (content_width, IMG_HEIGHT), color=TRANSPARENT_COLOR)
    text_layer_draw = ImageDraw.Draw(text_layer)

    text_y = 0

    if "text_zero" in texts:
        # Text one (Book title)
        text_zero = textwrap.fill(texts["text_zero"], width=72)
        text_layer_draw.multiline_text(
            (0, text_y), text_zero, font=font_text_zero, fill=TEXT_COLOR
        )

        text_y = text_y + font_text_zero.getsize_multiline(text_zero)[1] + 16

    if "text_one" in texts:
        # Text one (Book title)
        text_one = textwrap.fill(texts["text_one"], width=28)
        text_layer_draw.multiline_text(
            (0, text_y), text_one, font=font_text_one, fill=TEXT_COLOR
        )

        text_y = text_y + font_text_one.getsize_multiline(text_one)[1] + 16

    if "text_two" in texts:
        # Text one (Book subtitle)
        text_two = textwrap.fill(texts["text_two"], width=36)
        text_layer_draw.multiline_text(
            (0, text_y), text_two, font=font_text_two, fill=TEXT_COLOR
        )

        text_y = text_y + font_text_one.getsize_multiline(text_two)[1] + 16

    if "text_three" in texts:
        # Text three (Book authors)
        text_three = textwrap.fill(texts["text_three"], width=36)
        text_layer_draw.multiline_text(
            (0, text_y), text_three, font=font_text_three, fill=TEXT_COLOR
        )

    text_layer_box = text_layer.getbbox()
    return text_layer.crop(text_layer_box)


def generate_instance_layer(content_width):
    font_instance = get_font("light", size=28)

    site = models.SiteSettings.objects.get()

    if site.logo_small:
        logo_img = Image.open(site.logo_small)
    else:
        static_path = path.joinpath("static/images/logo-small.png")
        logo_img = Image.open(static_path)

    instance_layer = Image.new("RGBA", (content_width, 62), color=TRANSPARENT_COLOR)

    logo_img.thumbnail((50, 50), Image.ANTIALIAS)

    instance_layer.paste(logo_img, (0, 0))

    instance_layer_draw = ImageDraw.Draw(instance_layer)
    instance_layer_draw.text((60, 10), site.name, font=font_instance, fill=TEXT_COLOR)

    line_width = 50 + 10 + font_instance.getsize(site.name)[0]

    line_layer = Image.new(
        "RGBA", (line_width, 2), color=(*(ImageColor.getrgb(TEXT_COLOR)), 50)
    )
    instance_layer.alpha_composite(line_layer, (0, 60))

    return instance_layer


def generate_rating_layer(rating, content_width):
    icon_star_full = Image.open(path.joinpath("static/images/icons/star-full.png"))
    icon_star_empty = Image.open(path.joinpath("static/images/icons/star-empty.png"))
    icon_star_half = Image.open(path.joinpath("static/images/icons/star-half.png"))

    icon_size = 64
    icon_margin = 10

    rating_layer_base = Image.new(
        "RGBA", (content_width, icon_size), color=TRANSPARENT_COLOR
    )
    rating_layer_color = Image.new("RGBA", (content_width, icon_size), color=TEXT_COLOR)
    rating_layer_mask = Image.new(
        "RGBA", (content_width, icon_size), color=TRANSPARENT_COLOR
    )

    position_x = 0

    for r in range(math.floor(rating)):
        rating_layer_mask.alpha_composite(icon_star_full, (position_x, 0))
        position_x = position_x + icon_size + icon_margin

    if math.floor(rating) != math.ceil(rating):
        rating_layer_mask.alpha_composite(icon_star_half, (position_x, 0))
        position_x = position_x + icon_size + icon_margin

    for r in range(5 - math.ceil(rating)):
        rating_layer_mask.alpha_composite(icon_star_empty, (position_x, 0))
        position_x = position_x + icon_size + icon_margin

    rating_layer_mask = rating_layer_mask.getchannel("A")
    rating_layer_mask = ImageOps.invert(rating_layer_mask)

    rating_layer_composite = Image.composite(
        rating_layer_base, rating_layer_color, rating_layer_mask
    )

    return rating_layer_composite


def generate_default_inner_img():
    font_cover = get_font("light", size=28)

    default_cover = Image.new(
        "RGB", (inner_img_width, inner_img_height), color=DEFAULT_COVER_COLOR
    )
    default_cover_draw = ImageDraw.Draw(default_cover)

    text = "no image :("
    text_dimensions = font_cover.getsize(text)
    text_coords = (
        math.floor((inner_img_width - text_dimensions[0]) / 2),
        math.floor((inner_img_height - text_dimensions[1]) / 2),
    )
    default_cover_draw.text(text_coords, text, font=font_cover, fill="white")

    return default_cover


def generate_preview_image(
    texts={}, picture=None, rating=None, show_instance_layer=True
):
    # Cover
    try:
        inner_img_layer = Image.open(picture)
        inner_img_layer.thumbnail((inner_img_width, inner_img_height), Image.ANTIALIAS)
        color_thief = ColorThief(picture)
        dominant_color = color_thief.get_color(quality=1)
    except:
        inner_img_layer = generate_default_inner_img()
        dominant_color = ImageColor.getrgb(DEFAULT_COVER_COLOR)

    # Color
    if BG_COLOR in ["use_dominant_color_light", "use_dominant_color_dark"]:
        image_bg_color = "rgb(%s, %s, %s)" % dominant_color

        # Adjust color
        image_bg_color_rgb = [x / 255.0 for x in ImageColor.getrgb(image_bg_color)]
        image_bg_color_hls = colorsys.rgb_to_hls(*image_bg_color_rgb)

        if BG_COLOR == "use_dominant_color_light":
            lightness = max(0.9, image_bg_color_hls[1])
        else:
            lightness = min(0.15, image_bg_color_hls[1])

        image_bg_color_hls = (
            image_bg_color_hls[0],
            lightness,
            image_bg_color_hls[2],
        )
        image_bg_color = tuple(
            [math.ceil(x * 255) for x in colorsys.hls_to_rgb(*image_bg_color_hls)]
        )
    else:
        image_bg_color = BG_COLOR

    # Background (using the color)
    img = Image.new("RGBA", (IMG_WIDTH, IMG_HEIGHT), color=image_bg_color)

    # Contents
    inner_img_x = margin + inner_img_width - inner_img_layer.width
    inner_img_y = math.floor((IMG_HEIGHT - inner_img_layer.height) / 2)
    content_x = margin + inner_img_width + gutter
    content_width = IMG_WIDTH - content_x - margin

    contents_layer = Image.new(
        "RGBA", (content_width, IMG_HEIGHT), color=TRANSPARENT_COLOR
    )
    contents_composite_y = 0

    if show_instance_layer:
        instance_layer = generate_instance_layer(content_width)
        contents_layer.alpha_composite(instance_layer, (0, contents_composite_y))
        contents_composite_y = contents_composite_y + instance_layer.height + gutter

    texts_layer = generate_texts_layer(texts, content_width)
    contents_layer.alpha_composite(texts_layer, (0, contents_composite_y))
    contents_composite_y = contents_composite_y + texts_layer.height + gutter

    if rating:
        # Add some more margin
        contents_composite_y = contents_composite_y + gutter
        rating_layer = generate_rating_layer(rating, content_width)
        contents_layer.alpha_composite(rating_layer, (0, contents_composite_y))
        contents_composite_y = contents_composite_y + rating_layer.height + gutter

    contents_layer_box = contents_layer.getbbox()
    contents_layer_height = contents_layer_box[3] - contents_layer_box[1]

    contents_y = math.floor((IMG_HEIGHT - contents_layer_height) / 2)

    if show_instance_layer:
        # Remove Instance Layer from centering calculations
        contents_y = contents_y - math.floor((instance_layer.height + gutter) / 2)

    if contents_y < margin:
        contents_y = margin

    # Composite layers
    img.paste(
        inner_img_layer, (inner_img_x, inner_img_y), inner_img_layer.convert("RGBA")
    )
    img.alpha_composite(contents_layer, (content_x, contents_y))

    return img


def save_and_cleanup(image, instance=None):
    if instance:
        file_name = "%s.png" % str(uuid4())
        image_buffer = BytesIO()

        try:
            try:
                old_path = instance.preview_image.path
            except ValueError:
                old_path = ""

            # Save
            image.save(image_buffer, format="png")
            instance.preview_image = InMemoryUploadedFile(
                ContentFile(image_buffer.getvalue()),
                "preview_image",
                file_name,
                "image/png",
                image_buffer.tell(),
                None,
            )
            instance.save(update_fields=["preview_image"])

            # Clean up old file after saving
            if os.path.exists(old_path):
                os.remove(old_path)
        finally:
            image_buffer.close()


@app.task
def generate_site_preview_image_task():
    """generate preview_image for the website"""
    site = models.SiteSettings.objects.get()

    if site.logo:
        logo = site.logo
    else:
        logo = path.joinpath("static/images/logo.png")

    texts = {
        "text_zero": DOMAIN,
        "text_one": site.name,
        "text_three": site.instance_tagline,
    }

    image = generate_preview_image(texts=texts, picture=logo, show_instance_layer=False)

    save_and_cleanup(image, instance=site)


@app.task
def generate_edition_preview_image_task(book_id):
    """generate preview_image for a book"""
    book = models.Book.objects.select_subclasses().get(id=book_id)

    rating = models.Review.objects.filter(
        privacy="public",
        deleted=False,
        book__in=[book_id],
    ).aggregate(Avg("rating"))["rating__avg"]

    texts = {
        "text_one": book.title,
        "text_two": book.subtitle,
        "text_three": book.author_text,
    }

    image = generate_preview_image(texts=texts, picture=book.cover, rating=rating)

    save_and_cleanup(image, instance=book)


@app.task
def generate_user_preview_image_task(user_id):
    """generate preview_image for a book"""
    user = models.User.objects.get(id=user_id)

    texts = {
        "text_one": user.display_name,
        "text_three": "@{}@{}".format(user.localname, DOMAIN),
    }

    if user.avatar:
        avatar = user.avatar
    else:
        avatar = path.joinpath("static/images/default_avi.jpg")

    image = generate_preview_image(texts=texts, picture=avatar)

    save_and_cleanup(image, instance=user)
