from importlib.resources import files


def read_grammar() -> str:
    return files("arm_transpiller").joinpath("grammar.lark").read_text(encoding="utf-8")
