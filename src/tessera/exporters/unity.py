"""Unity target: writes ``<name>.png`` plus a ``.png.meta`` so Unity imports it
as pixel art with no further clicks: Sprite type, point filtering, no
mipmaps, no compression, the project's pixels-per-unit, a max size that
never downsamples, and the sprite slices.

The meta layout follows what Unity 6 (6000.x) writes itself. Re-exporting
keeps the asset's GUID, and sprite IDs are derived from GUID + sprite name,
so scene and prefab references survive a re-export as long as sprite names
stay the same.

Options (in the ``[[outputs]]`` entry): ``physics_shape`` (bool, default
true) and ``mesh`` ("full" or "tight", default "full").
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from tessera.config import PIVOTS
from tessera.exporters.base import ExportAsset, ExportError, Exporter, register

# UnityEngine.SpriteAlignment
ALIGNMENT = {
    "center": 0, "top-left": 1, "top": 2, "top-right": 3, "left": 4,
    "right": 5, "bottom-left": 6, "bottom": 7, "bottom-right": 8,
}
MAX_SIZES = (32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384)
PLATFORMS = ("DefaultTexturePlatform", "Standalone", "iOS", "Android")
GUID_LINE = re.compile(r"^guid:\s*([0-9a-f]{32})\s*$", re.MULTILINE)
KNOWN_OPTIONS = {"physics_shape", "mesh"}


@register
class UnityExporter(Exporter):
    target = "unity"

    def export(self, asset: ExportAsset) -> list[Path]:
        unknown = set(self.output.options) - KNOWN_OPTIONS
        if unknown:
            raise ExportError(f"unity output: unknown option(s) {', '.join(sorted(unknown))}")
        folder = self.output.path
        folder.mkdir(parents=True, exist_ok=True)
        png = folder / f"{asset.name}.png"
        meta = folder / f"{asset.name}.png.meta"
        asset.image.convert("RGBA").save(png, optimize=True)
        meta.write_text(self.meta_text(asset, existing_guid(meta)), encoding="utf-8", newline="\n")
        return [png, meta]

    def meta_text(self, asset: ExportAsset, guid: str | None = None) -> str:
        guid = guid or uuid.uuid4().hex
        width, height = asset.image.size
        max_size = next((s for s in MAX_SIZES if s >= max(width, height)), None)
        if max_size is None:
            raise ExportError(f"{asset.name}: {width}x{height} is larger than Unity's 16384 limit")
        options = self.output.options
        physics = 1 if options.get("physics_shape", True) else 0
        mesh = {"full": 0, "tight": 1}.get(options.get("mesh", "full"))
        if mesh is None:
            raise ExportError("unity output: mesh must be 'full' or 'tight'")

        single = (len(asset.sprites) == 1 and asset.sprites[0].name == asset.name
                  and (asset.sprites[0].width, asset.sprites[0].height) == (width, height)
                  and (asset.sprites[0].x, asset.sprites[0].y) == (0, 0))
        pivot_x, pivot_y = PIVOTS[asset.pivot]
        alignment = ALIGNMENT[asset.pivot]

        lines = [
            "fileFormatVersion: 2",
            f"guid: {guid}",
            "TextureImporter:",
        ]
        ids = {rect.name: internal_id(guid, rect.name) for rect in asset.sprites}
        if single:
            lines.append("  internalIDToNameTable: []")
        else:
            lines.append("  internalIDToNameTable:")
            for rect in asset.sprites:
                lines += ["  - first:", f"      213: {ids[rect.name]}", f"    second: {rect.name}"]
        lines += [
            "  externalObjects: {}",
            "  serializedVersion: 13",
            "  mipmaps:",
            "    mipMapMode: 0",
            "    enableMipMap: 0",
            "    sRGBTexture: 1",
            "    linearTexture: 0",
            "    fadeOut: 0",
            "    borderMipMap: 0",
            "    mipMapsPreserveCoverage: 0",
            "    alphaTestReferenceValue: 0.5",
            "    mipMapFadeDistanceStart: 1",
            "    mipMapFadeDistanceEnd: 3",
            "  bumpmap:",
            "    convertToNormalMap: 0",
            "    externalNormalMap: 0",
            "    heightScale: 0.25",
            "    normalMapFilter: 0",
            "    flipGreenChannel: 0",
            "  isReadable: 0",
            "  streamingMipmaps: 0",
            "  streamingMipmapsPriority: 0",
            "  vTOnly: 0",
            "  ignoreMipmapLimit: 0",
            "  grayScaleToAlpha: 0",
            "  generateCubemap: 6",
            "  cubemapConvolution: 0",
            "  seamlessCubemap: 0",
            "  textureFormat: 1",
            f"  maxTextureSize: {max_size}",
            "  textureSettings:",
            "    serializedVersion: 2",
            "    filterMode: 0",
            "    aniso: 1",
            "    mipBias: 0",
            "    wrapU: 1",
            "    wrapV: 1",
            "    wrapW: 1",
            "  nPOTScale: 0",
            "  lightmap: 0",
            "  compressionQuality: 50",
            f"  spriteMode: {1 if single else 2}",
            "  spriteExtrude: 1",
            f"  spriteMeshType: {mesh}",
            f"  alignment: {alignment}",
            f"  spritePivot: {{x: {pivot_x}, y: {pivot_y}}}",
            f"  spritePixelsToUnits: {self.project.grid.pixels_per_unit}",
            "  spriteBorder: {x: 0, y: 0, z: 0, w: 0}",
            f"  spriteGenerateFallbackPhysicsShape: {physics}",
            "  alphaUsage: 1",
            "  alphaIsTransparency: 1",
            "  spriteTessellationMethod: 0",
            "  spriteTessellationDetail: -1",
            "  spriteGeometrySubdivision: -1",
            "  textureType: 8",
            "  textureShape: 1",
            "  singleChannelComponent: 0",
            "  flipbookRows: 1",
            "  flipbookColumns: 1",
            "  maxTextureSizeSet: 0",
            "  compressionQualitySet: 0",
            "  textureFormatSet: 0",
            "  ignorePngGamma: 0",
            "  applyGammaDecoding: 0",
            "  swizzle: 50462976",
            "  cookieLightType: 0",
            "  platformSettings:",
        ]
        for platform in PLATFORMS:
            lines += [
                "  - serializedVersion: 4",
                f"    buildTarget: {platform}",
                f"    maxTextureSize: {max_size}",
                "    resizeAlgorithm: 0",
                "    textureFormat: -1",
                "    textureCompression: 0",
                "    compressionQuality: 50",
                "    crunchedCompression: 0",
                "    allowsAlphaSplitting: 0",
                "    overridden: 0",
                "    ignorePlatformSupport: 0",
                "    androidETC2FallbackOverride: 0",
                "    forceMaximumCompressionQuality_BC6H_BC7: 0",
            ]
        lines += ["  spriteSheet:", "    serializedVersion: 2"]
        if single:
            lines.append("    sprites: []")
        else:
            lines.append("    sprites:")
            for rect in asset.sprites:
                lines += [
                    "    - serializedVersion: 2",
                    f"      name: {rect.name}",
                    "      rect:",
                    "        serializedVersion: 2",
                    f"        x: {rect.x}",
                    # Unity rects start at the bottom-left corner.
                    f"        y: {height - rect.y - rect.height}",
                    f"        width: {rect.width}",
                    f"        height: {rect.height}",
                    f"      alignment: {alignment}",
                    f"      pivot: {{x: {pivot_x}, y: {pivot_y}}}",
                    "      border: {x: 0, y: 0, z: 0, w: 0}",
                    "      customData: ",
                    "      outline: []",
                    "      physicsShape: []",
                    "      tessellationDetail: -1",
                    "      bones: []",
                    f"      spriteID: {sprite_id(guid, rect.name)}",
                    f"      internalID: {ids[rect.name]}",
                    "      vertices: []",
                    "      indices: ",
                    "      edges: []",
                    "      weights: []",
                ]
        lines += [
            "    outline: []",
            "    customData: ",
            "    physicsShape: []",
            "    bones: []",
            # A single-mode sprite takes its ID from here; left empty, two
            # single sprites share one ID and Unity's sprite batching can draw
            # one with the other's texture.
            f"    spriteID: {sprite_id(guid, asset.name) if single else ''}",
            "    internalID: 0",
            "    vertices: []",
            "    indices: ",
            "    edges: []",
            "    weights: []",
            "    secondaryTextures: []",
            "    spriteCustomMetadata:",
            "      entries: []",
        ]
        if single:
            lines.append("    nameFileIdTable: {}")
        else:
            lines.append("    nameFileIdTable:")
            lines += [f"      {rect.name}: {ids[rect.name]}" for rect in asset.sprites]
        lines += [
            "  mipmapLimitGroupName: ",
            "  pSDRemoveMatte: 0",
            "  userData: ",
            "  assetBundleName: ",
            "  assetBundleVariant: ",
        ]
        return "\n".join(lines) + "\n"


def existing_guid(meta: Path) -> str | None:
    if not meta.is_file():
        return None
    match = GUID_LINE.search(meta.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _digest(guid: str, name: str) -> bytes:
    return hashlib.sha256(f"{guid}/{name}".encode()).digest()


def internal_id(guid: str, name: str) -> int:
    """A stable, non-zero signed 64-bit ID for a sprite of this texture."""
    value = int.from_bytes(_digest(guid, name)[:8], "little", signed=True)
    return value or 1


def sprite_id(guid: str, name: str) -> str:
    return _digest(guid, name)[8:24].hex()
