"""Tests for imaging module: OG image rendering with various templates and customizations."""

from app.imaging import TEMPLATES, render_og_image


class TestTemplatesList:
    """TEMPLATES constant tests."""

    def test_templates_is_list(self):
        """TEMPLATES is a list."""
        assert isinstance(TEMPLATES, list)

    def test_templates_contains_expected(self):
        """TEMPLATES contains expected template names."""
        assert "default" in TEMPLATES
        assert "dark" in TEMPLATES
        assert "gradient" in TEMPLATES
        assert "minimal" in TEMPLATES

    def test_templates_length(self):
        """TEMPLATES has exactly 4 templates."""
        assert len(TEMPLATES) == 4


class TestRenderOGImageBasic:
    """render_og_image basic functionality tests."""

    def test_render_og_image_returns_bytes(self):
        """render_og_image returns bytes."""
        result = render_og_image("Test Title")
        assert isinstance(result, bytes)

    def test_render_og_image_png_signature(self):
        """render_og_image returns PNG data (starts with PNG magic number)."""
        result = render_og_image("Test Title")
        assert result.startswith(b"\x89PNG")

    def test_render_og_image_minimal_title(self):
        """render_og_image works with minimal title."""
        result = render_og_image("Hi")
        assert result.startswith(b"\x89PNG")
        assert len(result) > 100  # Non-trivial PNG

    def test_render_og_image_long_title(self):
        """render_og_image wraps long titles."""
        long_title = "This is a very long title that should wrap to multiple lines when rendered on a 1200px canvas"
        result = render_og_image(long_title)
        assert result.startswith(b"\x89PNG")

    def test_render_og_image_with_subtitle(self):
        """render_og_image accepts subtitle parameter."""
        result = render_og_image("Title", subtitle="Subtitle here")
        assert result.startswith(b"\x89PNG")

    def test_render_og_image_empty_subtitle(self):
        """render_og_image works with empty subtitle (default)."""
        result = render_og_image("Title", subtitle="")
        assert result.startswith(b"\x89PNG")


class TestTemplateRendering:
    """Test rendering with each template."""

    def test_render_default_template(self):
        """render_og_image with template='default' works."""
        result = render_og_image("Title", template="default")
        assert result.startswith(b"\x89PNG")

    def test_render_dark_template(self):
        """render_og_image with template='dark' works."""
        result = render_og_image("Title", template="dark")
        assert result.startswith(b"\x89PNG")

    def test_render_gradient_template(self):
        """render_og_image with template='gradient' works."""
        result = render_og_image("Title", template="gradient")
        assert result.startswith(b"\x89PNG")

    def test_render_minimal_template(self):
        """render_og_image with template='minimal' works."""
        result = render_og_image("Title", template="minimal")
        assert result.startswith(b"\x89PNG")

    def test_render_invalid_template_fallback(self):
        """render_og_image with invalid template falls back to default."""
        result = render_og_image("Title", template="nonexistent")
        assert result.startswith(b"\x89PNG")

    def test_all_templates_render_different_images(self):
        """Different templates produce different images (different bytes)."""
        title = "Same Title"
        default = render_og_image(title, template="default")
        dark = render_og_image(title, template="dark")
        gradient = render_og_image(title, template="gradient")
        minimal = render_og_image(title, template="minimal")

        # They should be different (different color schemes)
        assert default != dark
        assert default != gradient
        assert default != minimal


class TestWatermark:
    """Watermark on/off tests."""

    def test_render_with_watermark_true(self):
        """render_og_image with watermark=True includes watermark."""
        result = render_og_image("Title", watermark=True)
        assert result.startswith(b"\x89PNG")

    def test_render_with_watermark_false(self):
        """render_og_image with watermark=False excludes watermark."""
        result = render_og_image("Title", watermark=False)
        assert result.startswith(b"\x89PNG")

    def test_watermark_on_off_different(self):
        """Images with watermark on/off are different."""
        on = render_og_image("Title", watermark=True)
        off = render_og_image("Title", watermark=False)
        # They should differ in size/content due to watermark text
        assert on != off


class TestCustomColors:
    """Custom color tests (bg/fg hex)."""

    def test_render_with_custom_bg(self):
        """render_og_image accepts bg hex color."""
        result = render_og_image("Title", bg="#0ea5e9")
        assert result.startswith(b"\x89PNG")

    def test_render_with_custom_fg(self):
        """render_og_image accepts fg hex color."""
        result = render_og_image("Title", fg="#ffffff")
        assert result.startswith(b"\x89PNG")

    def test_render_with_both_colors(self):
        """render_og_image accepts both bg and fg."""
        result = render_og_image("Title", bg="#1a1a1a", fg="#ffff00")
        assert result.startswith(b"\x89PNG")

    def test_render_invalid_hex_ignored(self):
        """render_og_image ignores invalid hex color and uses palette."""
        result = render_og_image("Title", bg="not-a-color", fg="also-bad")
        assert result.startswith(b"\x89PNG")

    def test_custom_colors_vs_template_palette(self):
        """Custom colors override template palette."""
        # Same title, different bg colors should produce different images
        default_palette = render_og_image("Title", template="default", bg=None)
        custom_bg = render_og_image("Title", template="default", bg="#ffff00")
        assert default_palette != custom_bg

    def test_render_bg_only(self):
        """render_og_image works with bg only, fg=None."""
        result = render_og_image("Title", bg="#ff0000", fg=None)
        assert result.startswith(b"\x89PNG")

    def test_render_fg_only(self):
        """render_og_image works with fg only, bg=None."""
        result = render_og_image("Title", bg=None, fg="#00ff00")
        assert result.startswith(b"\x89PNG")


class TestRenderConsistency:
    """Consistency and edge case tests."""

    def test_render_same_input_same_output(self):
        """Rendering the same input twice produces identical output."""
        result1 = render_og_image("Title", subtitle="Sub")
        result2 = render_og_image("Title", subtitle="Sub")
        # Deterministic rendering (same input -> same output)
        assert result1 == result2

    def test_render_unicode_title(self):
        """render_og_image handles unicode text."""
        result = render_og_image("Hello 世界 🌍")
        assert result.startswith(b"\x89PNG")

    def test_render_multiline_title(self):
        """render_og_image handles text with newlines."""
        result = render_og_image("Line 1\nLine 2")
        assert result.startswith(b"\x89PNG")

    def test_render_empty_title_with_subtitle(self):
        """render_og_image works with empty title but subtitle."""
        result = render_og_image("", subtitle="Only subtitle")
        assert result.startswith(b"\x89PNG")

    def test_render_special_characters(self):
        """render_og_image handles special characters."""
        result = render_og_image("Title & Special <Characters>")
        assert result.startswith(b"\x89PNG")
