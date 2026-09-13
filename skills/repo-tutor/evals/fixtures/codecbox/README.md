# Codecbox

Codecbox is a Python library, not a command-line application. Call `encode_text` to convert text into bytes using a named codec. Codecs implement the `Codec` protocol and are selected from a registry.

```python
from codecbox.api import encode_text

payload = encode_text("hello", codec="identity")
```

This example is documented but is not executed by a repository tutor.
