from dartfx.ckan import hello


def test_hello_default():
    assert hello() == "Hello, World!"


def test_hello_name():
    assert hello("Python") == "Hello, Python!"
