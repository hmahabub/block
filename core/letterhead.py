from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph

from .models import CompanyProfile

MAX_LETTERHEAD_HEIGHT = 45 * mm


def letterhead_flowables(width, name_style, sub_style):
    """Header flowables for a PDF: the letterhead image scaled to `width`, else the company text.

    Returns (flowables, profile). Falls back to text if the image is missing or unreadable, so a
    bad upload can never stop a report from printing.
    """
    profile = CompanyProfile.current()
    path = profile.letterhead_path
    if path:
        try:
            image_width, image_height = ImageReader(path).getSize()
            height = width * image_height / image_width
            if height > MAX_LETTERHEAD_HEIGHT:
                height = MAX_LETTERHEAD_HEIGHT
                width = height * image_width / image_height
            image = Image(path, width=width, height=height)
            image.hAlign = 'CENTER'
            return [image], profile
        except Exception:
            pass

    flowables = [Paragraph(profile.display_name, name_style)]
    if profile.display_address:
        flowables.append(Paragraph(profile.display_address.replace('\n', '<br/>'), sub_style))
    if profile.display_phone:
        flowables.append(Paragraph(f'Phone: {profile.display_phone}', sub_style))
    return flowables, profile
