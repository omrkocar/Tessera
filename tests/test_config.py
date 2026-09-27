import tomllib

import pytest

from conftest import CONFIG
from tessera.config import ConfigError, find_config, load_config, parse_config


def test_loads_and_fills_defaults(project_dir):
    project = load_config(project_dir)
    assert project.name == "test"
    assert len(project.palette) == 4
    assert project.grid.tile_size == 16
    assert project.shading.light_direction == "top-left"
    assert project.preview.background is None  # checkerboard
    assert project.output("unity").path == (project_dir / "unity_out").resolve()
    assert project.output("unity").pivot == "bottom"


def test_finds_config_in_parent_folder(project_dir):
    child = project_dir / "sprites" / "deep"
    child.mkdir(parents=True)
    assert find_config(child) == (project_dir / "tessera.toml").resolve()


def test_pixels_per_unit_defaults_to_tile_size(tmp_path):
    data = tomllib.loads(CONFIG)
    del data["grid"]["pixels_per_unit"]
    assert parse_config(data, tmp_path).grid.pixels_per_unit == 16


def test_collects_every_error(tmp_path):
    data = tomllib.loads(CONFIG)
    data["grid"]["tile_size"] = 0
    data["grid"]["tilesize"] = 16
    data["shading"] = {"light_direction": "sideways"}
    data["palette"]["max_colors"] = 2
    with pytest.raises(ConfigError) as error:
        parse_config(data, tmp_path)
    message = str(error.value)
    assert "grid.tile_size: must be at least 1" in message
    assert "grid.tilesize: unknown key" in message
    assert "shading.light_direction" in message
    assert "more than max_colors" in message


def test_palette_needs_exactly_one_source(tmp_path):
    data = tomllib.loads(CONFIG)
    data["palette"]["file"] = "p.hex"
    with pytest.raises(ConfigError, match="exactly one"):
        parse_config(data, tmp_path)


def test_output_options_pass_through(tmp_path):
    data = tomllib.loads(CONFIG)
    data["outputs"][0]["mesh"] = "tight"
    assert parse_config(data, tmp_path).output("unity").options == {"mesh": "tight"}


def test_missing_target_is_a_config_error(project_dir):
    with pytest.raises(ConfigError, match="no output with target 'godot'"):
        load_config(project_dir).output("godot")
