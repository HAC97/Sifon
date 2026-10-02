from app.runtimes import detect_js_runtime, js_runtimes_option


def only(*names):
    return lambda name: f"/bin/{name}" if name in names else None


def test_deno_is_preferred_over_node():
    assert detect_js_runtime(only("deno", "node")) == "deno"
    assert js_runtimes_option(only("deno", "node")) == {"deno": {}}


def test_node_is_the_fallback():
    assert detect_js_runtime(only("node")) == "node"
    assert js_runtimes_option(only("node")) == {"node": {}}


def test_no_runtime_means_an_empty_option_not_a_missing_one():
    assert detect_js_runtime(only()) is None
    assert js_runtimes_option(only()) == {}
