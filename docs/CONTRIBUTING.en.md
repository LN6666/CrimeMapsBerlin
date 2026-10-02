# Contributing to CrimeMaps Berlin

[English](CONTRIBUTING.en.md) · [Deutsch](CONTRIBUTING.de.md) · [中文](CONTRIBUTING.zh-CN.md)

Start with a small, reproducible change. Use the README commands to run the frontend. For code changes, run the checks affected by the change and describe the observed result in the pull request.

Use synthetic examples in tests. Keep police article bodies, databases, generated map datasets, local review evidence and credentials out of Git. A source correction needs the public article URL and the reason for the correction; it must not invent a time, address or coordinate.

Preserve report IDs, source links and location detail. A wording or translation change must keep the original meaning, uncertainty and upstream attribution. Public text should explain the map in everyday language; internal review details belong in local evidence.

A code merge and a map release are separate steps. Map publication requires the current source and location checks, the city data bundle and the release checks. Report security problems through the route described in SECURITY.md.
