# Marginalia Atlas

**Marginalia Atlas** is a spatial interface for exploring the semantic structure of a codebase.

It builds on the output of **Marginalia**, extending its inventory of functions, modules, and call relationships into a navigable 2-D atlas where code elements can be positioned, grouped, and revisited as part of a persistent cognitive map.

This is not UML, and it is not a diagram generator.  
Marginalia Atlas is a control panel for *thinking with code structure*.

---

## What It Does

- Loads Marginalia-generated inventories
- Represents code elements as spatially placeable objects
- Preserves layout as part of the data model
- Allows proximity and position to encode meaning
- Binds visual elements back to source, metadata, and callers

The goal is orientation, not compression.

---

## Relationship to Marginalia

Marginalia answers:

> *What exists in this codebase, and how is it connected?*

Marginalia Atlas adds:

> *Where do these things live in my understanding?*

---

## Installation

From a local checkout:

```bash
pip install -e .
