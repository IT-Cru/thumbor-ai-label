from __future__ import annotations

import itertools

import pytest
from PIL import Image, ImageChops, ImageStat

from thumbor_ai_label.compose import (
    Layout,
    Position,
    apply_label,
    fit_label,
    label_height,
    label_margin,
    label_origin,
    paste_label,
)
from thumbor_ai_label.detect import SourceType
from thumbor_ai_label.icons import (
    BUNDLED_SETS,
    LABEL_STATES,
    IconError,
    IconSet,
    _bundled_dir,
    set_directory,
)


class TestIconSet:
    def test_every_label_state_has_a_packaged_icon(self):
        icons = IconSet()
        for state in LABEL_STATES:
            assert icons.get(state, 32).height == 32

    def test_not_ai_has_no_icon(self):
        """A positively identified photograph gets no label, so needs no icon."""
        assert SourceType.NOT_AI not in LABEL_STATES
        with pytest.raises(IconError):
            IconSet().get(SourceType.NOT_AI, 32)

    def test_icons_are_rgba(self):
        assert IconSet().get(SourceType.AI_GENERATED, 48).mode == "RGBA"

    def test_resized_icons_are_cached(self):
        icons = IconSet()
        first = icons.get(SourceType.AI_GENERATED, 40)
        assert icons.get(SourceType.AI_GENERATED, 40) is first
        assert icons.cache_info().hits >= 1

    def test_opacity_scales_the_alpha_channel(self):
        full = IconSet().get(SourceType.UNKNOWN, 64).getchannel("A").getextrema()[1]
        half = IconSet(opacity=50).get(SourceType.UNKNOWN, 64).getchannel("A").getextrema()[1]
        assert half < full

    def test_zero_opacity_is_fully_transparent(self):
        assert IconSet(opacity=0).get(SourceType.UNKNOWN, 64).getchannel("A").getextrema() == (0, 0)

    @pytest.mark.parametrize("opacity", [-1, 101, 1000])
    def test_out_of_range_opacity_is_rejected(self, opacity):
        with pytest.raises(IconError):
            IconSet(opacity=opacity)

    def test_override_is_used(self, tmp_path):
        path = tmp_path / "custom.png"
        Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(path)
        icons = IconSet(overrides={"ai_generated": str(path)})
        assert icons.get(SourceType.AI_GENERATED, 64).getpixel((32, 32)) == (255, 0, 0, 255)

    def test_overriding_one_state_leaves_the_others_packaged(self, tmp_path):
        path = tmp_path / "custom.png"
        Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(path)
        icons = IconSet(overrides={"ai_generated": str(path)})
        assert icons.get(SourceType.UNKNOWN, 64).getpixel((32, 32)) != (255, 0, 0, 255)

    def test_a_missing_override_fails_at_construction(self, tmp_path):
        """Loudly at boot, not as a broken image mid-request."""
        with pytest.raises(IconError, match="not found"):
            IconSet(overrides={"ai_generated": str(tmp_path / "nope.png")})

    def test_a_corrupt_override_fails_at_construction(self, tmp_path):
        path = tmp_path / "bad.png"
        path.write_bytes(b"this is not a png")
        with pytest.raises(IconError, match="could not read"):
            IconSet(overrides={"ai_generated": str(path)})

    @pytest.mark.parametrize("value", ["", "   ", None, False, 0])
    def test_a_valueless_override_is_rejected_rather_than_falling_back(self, value):
        """Every one of these used to load the bundled icon and say nothing.

        `False` is the interesting one: it reads as an off switch, which is exactly
        the thing an operator would try before finding AI_LABEL_DRAW_STATES.
        """
        with pytest.raises(IconError, match="unusable icon override"):
            IconSet(overrides={"unknown": value})

    def test_the_rejection_points_at_the_key_that_does_suppress_a_state(self):
        with pytest.raises(IconError, match="AI_LABEL_DRAW_STATES"):
            IconSet(overrides={"unknown": ""})

    def test_a_padded_path_is_used_rather_than_reported_missing(self, tmp_path):
        """Whitespace is invisible in a config file and in the error it would cause."""
        path = tmp_path / "custom.png"
        Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(path)
        icons = IconSet(overrides={"unknown": f"  {path}  "})
        assert icons.get(SourceType.UNKNOWN, 64).getpixel((32, 32)) == (255, 0, 0, 255)

    def test_an_unknown_state_in_overrides_is_rejected(self):
        with pytest.raises(IconError, match="unknown label states"):
            IconSet(overrides={"ai_hallucinated": "nowhere/x.png"})

    def test_a_missing_packaged_icon_is_reported(self, tmp_path):
        # The set's directory exists but is empty, which is the case that has to
        # name the missing file rather than blame the set name.
        (tmp_path / "default").mkdir()
        with pytest.raises(IconError, match="is missing"):
            IconSet(icon_dir=tmp_path)

    def test_every_set_including_default_lives_in_its_own_subdirectory(self, tmp_path):
        """Uniform layout is what makes a directory of house sets drop straight in."""
        for name in BUNDLED_SETS:
            assert set_directory(name, tmp_path) == tmp_path / name

    def test_non_positive_height_is_rejected(self):
        with pytest.raises(IconError):
            IconSet().get(SourceType.AI_GENERATED, 0)


class TestLayoutValidation:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"size_ratio": 0},
            {"size_ratio": 1.5},
            {"margin_ratio": -0.1},
            {"margin_ratio": 0.6},
            {"min_size": 100, "max_size": 50},
            {"min_size": 0},
        ],
    )
    def test_nonsense_layouts_are_rejected(self, kwargs):
        with pytest.raises(ValueError):
            Layout(**kwargs)


class TestLabelHeight:
    def test_images_below_the_threshold_get_nothing(self):
        assert label_height((100, 100), Layout(min_image_size=120)) is None

    def test_size_tracks_the_shorter_edge(self):
        """Otherwise a label on a panorama looks tiny and on a tall crop looks absurd."""
        wide = label_height((3000, 400), Layout())
        tall = label_height((400, 3000), Layout())
        assert wide == tall

    def test_size_is_clamped_at_both_ends(self):
        assert label_height((200, 200), Layout(min_size=50, max_size=60)) == 50
        assert label_height((4000, 4000), Layout(min_size=10, max_size=64)) == 64

    def test_a_label_never_outgrows_its_frame(self):
        layout = Layout(size_ratio=1.0, min_size=1, max_size=10_000, min_image_size=1)
        size = label_height((150, 150), layout)
        assert size + 2 * label_margin((150, 150), layout) <= 150

    @pytest.mark.parametrize("size", [(0, 100), (100, 0), (0, 0)])
    def test_degenerate_sizes_yield_nothing(self, size):
        assert label_height(size, Layout(min_image_size=1)) is None


class TestLabelOrigin:
    @pytest.mark.parametrize(
        "position,expected_quadrant",
        [
            (Position.TOP_LEFT, (0, 0)),
            (Position.TOP_RIGHT, (1, 0)),
            (Position.BOTTOM_LEFT, (0, 1)),
            (Position.BOTTOM_RIGHT, (1, 1)),
        ],
    )
    def test_corners_land_in_the_right_quadrant(self, position, expected_quadrant):
        size = 40
        x, y = label_origin((400, 400), (size, size), Layout(position=position))
        assert (x > 200, y > 200) == (bool(expected_quadrant[0]), bool(expected_quadrant[1]))

    def test_center_is_centered(self):
        assert label_origin((400, 300), (40, 40), Layout(position=Position.CENTER)) == (180, 130)

    def test_origin_always_keeps_the_label_inside_the_frame(self):
        layout = Layout(margin_ratio=0.4, min_margin=0)
        for image_size in [(130, 400), (400, 130), (200, 200)]:
            size = label_height(image_size, layout) or 1
            x, y = label_origin(image_size, (size, size), layout)
            assert 0 <= x <= image_size[0] - size
            assert 0 <= y <= image_size[1] - size


class TestPaste:
    def icon(self):
        return Image.new("RGBA", (20, 20), (255, 0, 0, 255))

    def test_rgb_stays_rgb(self):
        result = paste_label(Image.new("RGB", (100, 100), (10, 10, 10)), self.icon(), (0, 0))
        assert result.mode == "RGB"
        assert result.getpixel((5, 5)) == (255, 0, 0)

    def test_rgba_keeps_its_alpha(self):
        result = paste_label(Image.new("RGBA", (100, 100), (0, 0, 0, 0)), self.icon(), (0, 0))
        assert result.mode == "RGBA"

    def test_greyscale_is_promoted_to_rgb(self):
        """An antialiased label cannot be composited without a colour mode."""
        result = paste_label(Image.new("L", (100, 100), 128), self.icon(), (0, 0))
        assert result.mode == "RGB"

    def test_palette_image_is_promoted(self):
        result = paste_label(Image.new("P", (100, 100)), self.icon(), (0, 0))
        assert result.mode == "RGB"

    def test_transparent_palette_keeps_its_alpha(self):
        source = Image.new("P", (100, 100))
        source.info["transparency"] = 0
        assert paste_label(source, self.icon(), (0, 0)).mode == "RGBA"

    def test_a_non_rgba_icon_is_converted(self):
        result = paste_label(
            Image.new("RGB", (100, 100)), Image.new("RGB", (20, 20), (0, 255, 0)), (0, 0)
        )
        assert result.getpixel((5, 5)) == (0, 255, 0)


class TestApplyLabel:
    def test_returns_false_when_the_image_is_too_small(self):
        image = Image.new("RGB", (50, 50))
        result, drawn = apply_label(image, lambda height: None, Layout())
        assert drawn is False
        assert result is image

    def test_the_icon_is_requested_at_the_chosen_size(self):
        asked = []

        def icon_for(height):
            asked.append(height)
            return Image.new("RGBA", (height, height), (255, 0, 0, 255))

        _, drawn = apply_label(Image.new("RGB", (400, 400)), icon_for, Layout())
        assert drawn is True
        assert asked[0] == label_height((400, 400), Layout())


def test_a_margin_that_swallows_the_frame_yields_no_label():
    layout = Layout(margin_ratio=0.49, min_margin=0, min_image_size=1)
    assert label_height((10, 10), layout) is None


#: The smallest label the plugin will draw, per AI_LABEL_MIN_SIZE's default.
MIN_LABEL_SIZE = 20

#: Mean absolute greyscale difference below which two states have collapsed into each
#: other. This is a collapse detector, not a measurement of ring geometry: the >=90 deg
#: gap constraint is enforced exactly by MIN_RING_GAP and check_gaps() in
#: tools/make_icons.py, which is the only place it can be checked as an angle rather
#: than inferred from pixels. The measured worst pair is ~15, so this leaves roughly 2x
#: headroom for deliberate design changes before the test needs revisiting.
COLLAPSE_FLOOR = 8.0


class TestIconSets:
    def test_every_bundled_set_loads_all_states(self):
        for name in BUNDLED_SETS:
            icons = IconSet(icon_set=name)
            for state in LABEL_STATES:
                assert icons.get(state, 32).height == 32

    def test_the_default_set_is_square(self):
        icons = IconSet()
        assert icons.aspect(SourceType.AI_GENERATED) == pytest.approx(1.0, abs=0.01)

    @pytest.mark.parametrize("name", ["eu", "eu-white"])
    def test_eu_labels_are_wide_lockups_not_squares(self, name):
        """The official marks are icon-plus-text; squashing them would deform them."""
        icons = IconSet(icon_set=name)
        assert icons.aspect(SourceType.AI_GENERATED) > 2.5
        icon = icons.get(SourceType.AI_GENERATED, 40)
        assert icon.height == 40
        assert icon.width > 100

    #: Each EU set borrows its neutral mark from the variant tuned for the same
    #: imagery, so a white EU label is never paired with a dark unknown.
    @pytest.mark.parametrize("name,own", [("eu", "default"), ("eu-white", "default-light")])
    def test_unknown_never_uses_an_official_eu_mark(self, name, own):
        """The EU marks assert content IS AI. Unproven provenance is not that claim."""
        eu = IconSet(icon_set=name)
        ours = IconSet(icon_set=own)
        assert (
            eu.get(SourceType.UNKNOWN, 64).tobytes() == ours.get(SourceType.UNKNOWN, 64).tobytes()
        )
        assert eu.aspect(SourceType.UNKNOWN) == pytest.approx(1.0, abs=0.01)

    def test_the_two_default_variants_differ(self):
        dark = IconSet(icon_set="default").get(SourceType.AI_GENERATED, 40)
        light = IconSet(icon_set="default-light").get(SourceType.AI_GENERATED, 40)
        assert dark.tobytes() != light.tobytes()

    @pytest.mark.parametrize("name", ["default", "default-light"])
    def test_default_variants_are_square(self, name):
        icons = IconSet(icon_set=name)
        for state in LABEL_STATES:
            assert icons.aspect(state) == pytest.approx(1.0, abs=0.01)

    @pytest.mark.parametrize("name", ["default", "default-light"])
    @pytest.mark.parametrize("size", [MIN_LABEL_SIZE, 32])
    def test_each_default_state_is_visually_distinct(self, name, size):
        """Survives greyscale printing and colour blindness at the smallest label drawn.

        Asserted at 20 px as well as a comfortable size, because 20 px is where a ring
        break pattern is at risk of closing up under the downscale — and where the set
        previously failed while still passing a distinctness check run at 32 px.
        """
        icons = IconSet(icon_set=name)

        rendered = {}
        for state in LABEL_STATES:
            icon = icons.get(state, size)
            # Composited onto mid-grey: the discs are translucent, and comparing raw
            # RGBA would let an alpha difference stand in for a visible one.
            ground = Image.new("RGBA", icon.size, (128, 128, 128, 255))
            ground.alpha_composite(icon)
            rendered[state] = ground.convert("L")

        assert len({image.tobytes() for image in rendered.values()}) == len(LABEL_STATES)

        for first, second in itertools.combinations(LABEL_STATES, 2):
            difference = ImageChops.difference(rendered[first], rendered[second])
            mean = ImageStat.Stat(difference).mean[0]
            assert mean >= COLLAPSE_FLOOR, (
                f"{first.value} and {second.value} are within {mean:.1f} mean grey levels "
                f"at {size}px in the {name!r} set"
            )

    def test_composite_uses_the_modified_mark(self):
        """A composite containing AI elements is 'partially modified with AI'."""
        icons = IconSet(icon_set="eu")
        assert (
            icons.get(SourceType.AI_COMPOSITE, 40).tobytes()
            == icons.get(SourceType.AI_MANIPULATED, 40).tobytes()
        )

    def test_the_two_eu_variants_differ(self):
        black = IconSet(icon_set="eu").get(SourceType.AI_GENERATED, 40)
        white = IconSet(icon_set="eu-white").get(SourceType.AI_GENERATED, 40)
        assert black.tobytes() != white.tobytes()

    def test_an_unknown_set_name_is_rejected(self):
        with pytest.raises(IconError, match="unknown icon set"):
            IconSet(icon_set="klingon")

    def test_overrides_still_win_within_a_set(self, tmp_path):
        path = tmp_path / "custom.png"
        Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(path)
        icons = IconSet(icon_set="eu", overrides={"ai_generated": str(path)})
        assert icons.get(SourceType.AI_GENERATED, 64).getpixel((32, 32)) == (255, 0, 0, 255)


class TestNonSquareFitting:
    WIDE = (900, 300)  # a 3:1 lockup

    def test_height_drives_size_and_width_follows(self):
        fitted = fit_label((800, 600), self.WIDE, Layout())
        assert fitted is not None
        width, height = fitted
        assert width / height == pytest.approx(3.0, abs=0.05)

    def test_a_wide_label_is_scaled_down_to_fit_a_narrow_image(self):
        """Scaling preserves the mark; squashing to fit would deform it."""
        layout = Layout(size_ratio=0.9, min_size=1, max_size=10_000, min_image_size=1)
        image_size = (200, 400)
        fitted = fit_label(image_size, self.WIDE, layout)
        width, height = fitted
        margin = label_margin(image_size, layout)
        assert width <= image_size[0] - 2 * margin
        assert width / height == pytest.approx(3.0, abs=0.05)

    def test_a_fitted_label_always_lands_inside_the_frame(self):
        for position in Position:
            layout = Layout(position=position)
            for image_size in [(400, 300), (300, 400), (1200, 200)]:
                fitted = fit_label(image_size, self.WIDE, layout)
                if fitted is None:
                    continue
                x, y = label_origin(image_size, fitted, layout)
                assert 0 <= x <= image_size[0] - fitted[0]
                assert 0 <= y <= image_size[1] - fitted[1]

    def test_a_degenerate_icon_yields_nothing(self):
        assert fit_label((400, 300), (0, 10), Layout()) is None
        assert fit_label((400, 300), (10, 0), Layout()) is None

    def test_too_small_an_image_yields_nothing(self):
        assert fit_label((50, 50), self.WIDE, Layout()) is None

    def test_no_horizontal_room_yields_nothing(self):
        layout = Layout(margin_ratio=0.49, min_margin=0, min_image_size=1)
        assert fit_label((10, 400), self.WIDE, layout) is None

    def test_apply_label_draws_a_wide_lockup_undistorted(self):
        icons = IconSet(icon_set="eu")
        image = Image.new("RGB", (800, 600), (120, 120, 120))
        result, drawn = apply_label(
            image, lambda h: icons.get(SourceType.AI_GENERATED, h), Layout()
        )
        assert drawn is True
        assert result.size == (800, 600)


class TestApplyLabelEdges:
    def test_an_icon_provider_returning_nothing_draws_nothing(self):
        image = Image.new("RGB", (400, 300))
        result, drawn = apply_label(image, lambda h: None, Layout())
        assert drawn is False
        assert result is image

    def test_no_horizontal_room_draws_nothing(self):
        """Tall enough for a label, too narrow for one once margins are taken."""
        layout = Layout(margin_ratio=0.49, min_margin=0, min_image_size=1)
        image = Image.new("RGB", (10, 400))
        result, drawn = apply_label(
            image, lambda h: Image.new("RGBA", (900, 300), (255, 0, 0, 255)), layout
        )
        assert drawn is False
        assert result is image

    def test_an_oversized_lockup_is_rescaled_not_squashed(self):
        """Exercises the shrink path: a wide mark that will not fit at its height."""
        icons = IconSet(icon_set="eu")
        layout = Layout(size_ratio=0.5, min_size=1, max_size=10_000)
        image = Image.new("RGB", (400, 400), (120, 120, 120))

        requested = []

        def icon_for(height):
            requested.append(height)
            return icons.get(SourceType.AI_GENERATED, height)

        result, drawn = apply_label(image, icon_for, layout)
        assert drawn is True
        assert len(requested) == 2, "should re-request from source artwork, not rescale a copy"
        assert requested[1] < requested[0]
        assert result.size == (400, 400)

    def test_the_rescale_fallback_still_produces_the_fitted_size(self):
        """If the provider ignores the corrected height, force the size anyway."""
        layout = Layout(size_ratio=0.5, min_size=1, max_size=10_000)
        image = Image.new("RGB", (400, 400))
        stubborn = Image.new("RGBA", (900, 300), (255, 0, 0, 255))

        result, drawn = apply_label(image, lambda h: stubborn, layout)
        assert drawn is True
        assert result.size == (400, 400)


class TestBundledDirResolution:
    """The artwork lives outside src/, so two locations have to be tried.

    A wheel gets it at ``thumbor_ai_label/labelsets/`` (mapped in by pyproject);
    a checkout with an editable install has only the repository's ``ai-labels/``.
    """

    def test_the_resolved_directory_holds_every_bundled_set(self):
        for name in BUNDLED_SETS:
            assert set_directory(name).is_dir(), name

    def test_the_packaged_location_wins_over_the_checkout(self, tmp_path):
        packaged = tmp_path / "labelsets"
        packaged.mkdir()
        checkout = tmp_path / "ai-labels"
        checkout.mkdir()
        assert _bundled_dir((packaged, checkout)) == packaged

    def test_the_checkout_location_is_used_when_nothing_is_packaged(self, tmp_path):
        checkout = tmp_path / "ai-labels"
        checkout.mkdir()
        assert _bundled_dir((tmp_path / "labelsets", checkout)) == checkout

    def test_a_broken_install_reports_the_packaged_location(self, tmp_path):
        """Not a crash at import: IconSet raises later, naming a path worth fixing."""
        packaged = tmp_path / "labelsets"
        assert _bundled_dir((packaged, tmp_path / "ai-labels")) == packaged
