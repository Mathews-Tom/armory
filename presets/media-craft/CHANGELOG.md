# Changelog

## 1.1.2

- Rename-only consumer migration: the optional companion `concept-to-video` is now `animate` (2.0.0, no alias). Routing precedence is unchanged. The preset stays deprecated in favor of the `media-producer` agent.

## 1.1.1

- Add the standalone `html-video` skill (HTML and CSS rendered with Hyperframes) to the optional companion list and routing table of this deprecated preset. An explicit engine request outranks content type, and a plain web page with no video output is not a video request. Add evaluation cases for HTML video routing and a plain HTML page. The preset stays deprecated in favor of the `media-producer` agent.
