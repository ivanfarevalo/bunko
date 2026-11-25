# Third-party notices

Bunko bundles these front-end libraries in `bunko/static/vendor/`, so it works
without internet access. Each keeps its own license; full texts are in
`bunko/static/vendor/LICENSES/`.

| Library | Version | License | File |
|---|---|---|---|
| [marked](https://github.com/markedjs/marked) | 18.1.3 | MIT | `LICENSES/marked.txt` |
| [DOMPurify](https://github.com/cure53/DOMPurify) | 3.5.0 | Apache-2.0 or MPL-2.0, at your option | `LICENSES/dompurify-apache-2.0.txt`, `LICENSES/dompurify-mpl-2.0.txt` |
| [highlight.js](https://github.com/highlightjs/highlight.js) | 11.11.1 | BSD-3-Clause | `LICENSES/highlight.js.txt` |

Bunko can also call these programs when they're installed. They aren't bundled
or required:

- [FFmpeg](https://ffmpeg.org/), meaning `ffmpeg` and `ffprobe`, for thumbnails and video facts.
- [ripgrep](https://github.com/BurntSushi/ripgrep), meaning `rg`, for content search.
