"""Executable design profile for self-contained static SVG; no network access."""

import math
import re
import unittest
from xml.parsers import expat

from PIL import ImageColor

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
NUMBER = r"[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][-+]?[0-9]+)?"
ID = r"[A-Za-z_][A-Za-z0-9_.-]*"
COMMON = {"id", "transform", "fill", "stroke", "stroke-width", "opacity",
          "fill-opacity", "stroke-opacity", "fill-rule", "stroke-linecap",
          "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset"}
ATTRS = {
    "svg": {"x", "y", "width", "height", "viewBox", "preserveAspectRatio"},
    "g": set(), "defs": set(),
    "rect": {"x", "y", "width", "height", "rx", "ry"},
    "circle": {"cx", "cy", "r"}, "ellipse": {"cx", "cy", "rx", "ry"},
    "line": {"x1", "y1", "x2", "y2"},
    "polyline": {"points"}, "polygon": {"points"}, "path": {"d"},
    "linearGradient": {"x1", "y1", "x2", "y2", "gradientUnits", "gradientTransform", "spreadMethod", "href"},
    "radialGradient": {"cx", "cy", "r", "fx", "fy", "fr", "gradientUnits", "gradientTransform", "spreadMethod", "href"},
    "stop": {"offset", "stop-color", "stop-opacity"},
    "use": {"x", "y", "width", "height", "href"}, "title": set(), "desc": set(),
}
GEOMETRY = {"rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "use"}
GRADIENTS = {"linearGradient", "radialGradient"}
ENUMS = {
    "fill-rule": {"nonzero", "evenodd"}, "stroke-linecap": {"butt", "round", "square"},
    "stroke-linejoin": {"miter", "round", "bevel"},
    "gradientUnits": {"userSpaceOnUse", "objectBoundingBox"},
    "spreadMethod": {"pad", "reflect", "repeat"},
}


class SvgRejected(ValueError):
    """Expose a fixed classification without embedding source content."""


def reject():
    """Reject data outside this deliberately finite profile."""
    raise SvgRejected("UNSUPPORTED_IMAGE")


def numbers(value):
    """Parse a complete finite SVG number list, rejecting leftover syntax."""
    if not value.strip() or re.search(r",\s*,|^\s*,|,\s*$", value):
        reject()
    tokens = re.findall(NUMBER, value)
    if re.sub(NUMBER, "", value).strip(" ,\t\r\n"):
        reject()
    result = [float(token) for token in tokens]
    if not result or not all(math.isfinite(n) for n in result):
        reject()
    return result


def transform(value):
    """Validate the supported SVG transform functions and argument counts."""
    counts = {"matrix": {6}, "translate": {1, 2}, "scale": {1, 2},
              "rotate": {1, 3}, "skewX": {1}, "skewY": {1}}
    parts = list(re.finditer(r"([A-Za-z]+)\s*\(([^()]*)\)", value))
    if not parts or re.sub(r"[A-Za-z]+\s*\([^()]*\)", "", value).strip(" ,\t\r\n"):
        reject()
    for part in parts:
        if part[1] not in counts or len(numbers(part[2])) not in counts[part[1]]:
            reject()


def path_data(value):
    """Validate explicit path command groups, including arc flags and radii."""
    if not value.strip():
        return
    commands = "MmZzLlHhVvCcSsQqTtAa"
    if re.search(r"[A-Za-z]\s*,|,\s*,|,\s*$", value):
        reject()
    groups = list(re.finditer(r"([" + commands + r"])([^" + commands + r"]*)", value))
    if not groups or groups[0].start() != len(value) - len(value.lstrip()) or groups[0][1] not in "Mm":
        reject()
    sizes = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}
    for group in groups:
        command = group[1].upper()
        if command == "Z":
            if group[2].strip():
                reject()
            continue
        values = numbers(group[2])
        size = sizes[command]
        if len(values) % size:
            reject()
        if command == "A":
            for start in range(0, len(values), 7):
                if values[start] < 0 or values[start + 1] < 0 or any(values[start + n] not in (0, 1) for n in (3, 4)):
                    reject()


def validate_svg(data):
    """Validate namespaces, finite attributes and acyclic local references."""
    parser = expat.ParserCreate(namespace_separator="|")
    nodes, stack, ids, references = [], [], {}, []

    def unsupported(*args):
        """Reject declarations or processing instructions before expansion."""
        reject()

    def namespace(prefix, uri):
        """Reject namespaces outside SVG and the local href-only XLink form."""
        if uri not in (SVG, XLINK):
            reject()

    def start(name, attrs):
        """Check the element, containment and every explicitly allowed attribute."""
        if not name.startswith(SVG + "|") or name.split("|")[-1] not in ATTRS:
            reject()
        tag = name.split("|")[-1]
        if not nodes and tag != "svg":
            reject()
        if stack:
            parent = nodes[stack[-1]]["tag"]
            allowed = {"title", "desc"}
            if parent in {"svg", "g", "defs"}:
                allowed |= GEOMETRY | {"svg", "g", "defs"} | GRADIENTS
            elif parent in GRADIENTS:
                allowed |= {"stop"}
            elif parent in {"title", "desc", "stop"}:
                allowed = set()
            if tag not in allowed:
                reject()
        index = len(nodes)
        node = {"tag": tag, "edges": []}
        nodes.append(node)
        if stack:
            nodes[stack[-1]]["edges"].append(index)
        stack.append(index)
        local_attrs = set()
        for full, raw in attrs.items():
            key = full
            if "|" in full:
                if full != XLINK + "|href":
                    reject()
                key = "href"
            if key in local_attrs or key not in COMMON | ATTRS[tag]:
                reject()
            local_attrs.add(key)
            value = raw.strip()
            if key == "id":
                if raw != value or not re.fullmatch(ID, value) or value in ids:
                    reject()
                ids[value] = index
            elif key == "href":
                if not re.fullmatch("#" + ID, value):
                    reject()
                references.append((index, value[1:], "href"))
            elif key in {"fill", "stroke", "stop-color"}:
                if key == "stop-color" and value == "none":
                    reject()
                ref = re.fullmatch(r"url\(#(" + ID + r")\)", value)
                if ref and key in {"fill", "stroke"}:
                    references.append((index, ref[1], "paint"))
                elif value not in {"none", "transparent"} and value.lower() not in ImageColor.colormap and not re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", value):
                    reject()
            elif key in {"transform", "gradientTransform"}:
                transform(value)
            elif key in ENUMS:
                if value not in ENUMS[key]:
                    reject()
            elif key == "viewBox":
                parts = numbers(value)
                if len(parts) != 4 or min(parts[2:]) <= 0:
                    reject()
            elif key == "preserveAspectRatio":
                if not re.fullmatch(r"none|x(?:Min|Mid|Max)Y(?:Min|Mid|Max)(?:\s+(?:meet|slice))?", value):
                    reject()
            elif key == "d":
                path_data(value)
            elif key == "points":
                parts = numbers(value)
                if len(parts) % 2 or len(parts) < (6 if tag == "polygon" else 4):
                    reject()
            elif key == "stroke-dasharray":
                if value != "none" and any(n < 0 for n in numbers(value)):
                    reject()
            elif key in {"opacity", "fill-opacity", "stroke-opacity", "stop-opacity", "offset", "stroke-miterlimit"}:
                parts = numbers(value)
                if len(parts) != 1 or (parts[0] < 1 if key == "stroke-miterlimit" else not 0 <= parts[0] <= 1):
                    reject()
            else:
                match = re.fullmatch("(" + NUMBER + r")(?:px|pt|pc|in|cm|mm|%)?", value)
                if not match or not math.isfinite(float(match[1])):
                    reject()
                if key in {"width", "height", "r", "rx", "ry", "fr", "stroke-width"} and float(match[1]) < 0:
                    reject()

    def end(name):
        """Maintain the element stack for reference and text validation."""
        stack.pop()

    def text(value):
        """Allow descriptive text only where the finite profile preserves it."""
        if value.strip() and (not stack or nodes[stack[-1]]["tag"] not in {"title", "desc"}):
            reject()

    parser.StartNamespaceDeclHandler = namespace
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.StartDoctypeDeclHandler = unsupported
    parser.EntityDeclHandler = unsupported
    parser.ExternalEntityRefHandler = unsupported
    parser.ProcessingInstructionHandler = unsupported
    parser.Parse(data, True)
    for source, target_id, kind in references:
        if target_id not in ids:
            reject()
        target = ids[target_id]
        source_tag, target_tag = nodes[source]["tag"], nodes[target]["tag"]
        if kind == "paint" and target_tag not in GRADIENTS:
            reject()
        if kind == "href" and ((source_tag in GRADIENTS and target_tag != source_tag) or (source_tag == "use" and target_tag not in GEOMETRY | {"g", "svg"})):
            reject()
        nodes[source]["edges"].append(target)
    visited, active = set(), set()

    def visit(index):
        """Reject local reference cycles including use-to-ancestor cycles."""
        if index in active:
            reject()
        if index in visited:
            return
        active.add(index)
        for target in nodes[index]["edges"]:
            visit(target)
        active.remove(index)
        visited.add(index)

    visit(0)
    return len(nodes)


class SvgProfileTests(unittest.TestCase):
    """Exercise valid examples and malformed/unsupported boundary inputs."""

    def test_valid_static_examples(self):
        """Preserve local shapes, gradients, references, paths and transforms."""
        examples = [
            '<rect width="8" height="6" fill="red"/>',
            '<defs><linearGradient id="g"><stop offset="0" stop-color="#abc"/></linearGradient></defs><rect width="8" height="6" fill="url(#g)"/>',
            '<defs><rect id="r" width="2" height="3"/></defs><use href="#r" x="1"/>',
            '<path d="M0 0 L8 0 8 6 Z" transform="translate(1,2) rotate(30)"/>',
            '<path d="M0 0 A2 3 0 0 1 4 5"/>',
            '<polygon points="0,0 8,0 4,6" fill="#ff000080"/>',
            '<g id="shapes" opacity="0.5" fill-opacity="0.8" stroke-opacity="1" fill-rule="evenodd" stroke="blue" stroke-width="1px" stroke-linecap="round" stroke-linejoin="bevel" stroke-miterlimit="2" stroke-dasharray="1 2" stroke-dashoffset="-1"><circle cx="2" cy="2" r="1"/><ellipse cx="4" cy="2" rx="1" ry="2"/><line x1="0" y1="0" x2="8" y2="6"/><polyline points="0 0 8 6"/></g>',
            '<defs><radialGradient id="r" cx="0.5" cy="0.5" r="0.5" fx="0.2" fy="0.2" fr="0" gradientUnits="objectBoundingBox" spreadMethod="reflect" gradientTransform="matrix(1 0 0 1 0 0)"><stop offset="1" stop-color="blue" stop-opacity="0.5"/></radialGradient></defs><rect width="8" height="6" fill="url(#r)"/>',
            '<svg viewBox="0 0 8 6" preserveAspectRatio="xMidYMid meet"><title>Dummy</title><desc>Local only</desc><path d="M0 0h1v1c1 0 1 1 2 2s1 1 2 2q1 1 2 2t1 1z" transform="scale(1,1) skewX(1) skewY(1)"/></svg>',
            '<defs><linearGradient id="a" href="#b"/><linearGradient id="b"><stop offset="0" stop-color="red"/></linearGradient></defs><rect width="8" height="6" fill="url(#a)"/>',
            '<defs><rect id="r" width="8" height="6"/></defs><use xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="#r"/>',
        ]
        for content in examples:
            with self.subTest(content=content):
                self.assertGreater(validate_svg(('<svg xmlns="' + SVG + '" width="8" height="6">' + content + '</svg>').encode()), 1)

    def test_unsupported_boundaries(self):
        """Reject active, external, ambiguous and unknown syntax without fetching."""
        examples = [
            '<script/>', '<rect onclick="x"/>', '<foreignObject/>', '<animate/>',
            '<style/>', '<rect style="fill:red"/>', '<text>font</text>',
            '<image href="data:image/png;base64,eA=="/>', '<rect class="unknown"/>',
            '<rect custom="x"/>', '<use href="https://example.invalid/a"/>',
            '<use href="#missing"/>', '<g id="g"><use href="#g"/></g>',
            '<rect id="a"/><rect id="a"/>', '<rect fill="url(https://example.invalid/a)"/>',
            '<rect fill="URL(#g)"/>', '<rect fill="url(\"#g\")"/>',
            '<rect fill="var(--paint)"/>', '<rect width="NaN"/>', '<rect width="1e999"/>',
            '<rect width="-1"/>', '<path d="M0 0 L1"/>', '<path d="M0 0 A1 1 0 2 0 4 4"/>',
            '<path d="L0 0"/>', '<rect transform="translate(1) unknown(2)"/>',
            '<rect transform="matrix(1,2)"/>', '<x xmlns="urn:unknown"/>',
            '<g xmlns:q="urn:unknown"/>', '<stop offset="0"/>',
            '<rect id=" padded "/><use href="#padded"/>',
            '<defs><linearGradient id="a" href="#b"/><linearGradient id="b" href="#a"/></defs>',
            '<rect id="r"/><rect fill="url(#r)"/>',
            '<defs><linearGradient id="a"/><radialGradient href="#a"/></defs>',
            '<rect id="r"/><use href="#r" xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="#r"/>',
            '<svg viewBox="0 0 -1 2"/>', '<svg preserveAspectRatio="unknown"/>',
            '<rect opacity="2"/>', '<rect stroke-miterlimit="0"/>', '<rect stroke-dasharray="-1 2"/>',
            '<polygon points="0 0 1"/>', '<path d="M,0 0"/>', '<rect fill="notacolor"/>',
            '<rect xml:base="https://example.invalid/"/>',
            '<defs><linearGradient><stop stop-color="none"/></linearGradient></defs>',
        ]
        for content in examples:
            with self.subTest(content=content), self.assertRaises((SvgRejected, expat.ExpatError)):
                validate_svg(('<svg xmlns="' + SVG + '">' + content + '</svg>').encode())
        for raw in (b'<!DOCTYPE svg [<!ENTITY x "x">]><svg/>', b'<?xml-stylesheet href="x"?><svg/>', b'<svg', b'<html/>'):
            with self.subTest(raw=raw), self.assertRaises((SvgRejected, expat.ExpatError)):
                validate_svg(raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
