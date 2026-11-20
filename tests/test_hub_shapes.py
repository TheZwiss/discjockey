"""The shapes kernel (issue 39, phase 2, design §8.2): the closed set of constructs, what it refuses, how a subclass
and a value are read. Each test makes its own `Registry`, so none touches the product's `SHAPES`."""
from typing import Annotated, Any, Literal, NotRequired, TypedDict

import pytest

from discjockey.hub.shapes import kernel
from discjockey.hub.shapes.kernel import F, Registry, ShapeError


def make() -> Registry:
    return Registry()


# --- constructs: each one round-trips to JSON Schema and TypeScript exactly ---

def construct(tp, *, required: bool = True):
    """A one-field shape `Box` holding `tp`, in a fresh registry: (registry, its JSON property, its TS lines)."""
    reg = make()

    class Box(TypedDict):
        """A box."""
        v: Annotated[tp, F("the value")] if required else NotRequired[Annotated[tp, F("the value")]]

    reg.shape(Box)
    return reg


def prop(reg: Registry) -> dict:
    p = reg.definition("Box")["properties"]["v"]
    return {k: v for k, v in p.items() if k not in ("description", "x-shown")}


def ts_field(reg: Registry) -> str:
    return next(line for line in reg.typescript().splitlines() if line.startswith("  v"))


@pytest.mark.parametrize("tp, schema, ts", [
    (str, {"type": "string"}, "v: string;"),
    (int, {"type": "integer"}, "v: number;"),
    (float, {"type": "number"}, "v: number;"),
    (bool, {"type": "boolean"}, "v: boolean;"),
    (Literal["a", "b"], {"enum": ["a", "b"]}, "v: 'a' | 'b';"),
    (Literal[False], {"const": False}, "v: false;"),
    (Literal[3, 4], {"enum": [3, 4]}, "v: 3 | 4;"),
    (str | None, {"anyOf": [{"type": "string"}, {"type": "null"}]}, "v: string | null;"),
    (list[int], {"type": "array", "items": {"type": "integer"}}, "v: number[];"),
    (list[str | None], {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
     "v: (string | null)[];"),
    (dict[str, bool], {"type": "object", "additionalProperties": {"type": "boolean"}}, "v: Record<string, boolean>;"),
    (tuple[str, bool], {"type": "array", "prefixItems": [{"type": "string"}, {"type": "boolean"}], "items": False,
                        "minItems": 2, "maxItems": 2}, "v: [string, boolean];"),
    (Any, {}, "v: any;"),
])
def test_each_construct_round_trips_to_json_schema_and_typescript(tp, schema, ts):
    reg = construct(tp)
    assert prop(reg) == schema
    assert ts_field(reg) == "  " + ts


def test_a_key_that_may_be_absent_is_optional_in_both():
    reg = construct(int, required=False)
    assert "required" not in reg.definition("Box")
    assert ts_field(reg) == "  v?: number;"


def test_the_other_nesting_of_not_required_is_read_too():
    reg = make()

    class Box(TypedDict):
        v: Annotated[NotRequired[int], F("x")]

    reg.shape(Box)
    assert "required" not in reg.definition("Box")


def test_nested_shapes_and_aliases_are_named_in_both():
    reg = make()
    Kind = reg.alias("Kind", Literal["x", "y"], const="KINDS", doc="A kind.")

    @reg.shape
    class Inner(TypedDict):
        """Inside."""
        k: Annotated[Kind, F("the kind")]

    @reg.shape
    class Outer(TypedDict):
        """Outside."""
        inner: Annotated[Inner, F("one")]
        many: Annotated[list[Inner], F("several")]
        maybe: Annotated[Kind | None, F("kind or none")]

    props = reg.definition("Outer")["properties"]
    assert props["inner"]["$ref"] == "#/$defs/Inner" and props["many"]["items"] == {"$ref": "#/$defs/Inner"}
    assert props["maybe"]["anyOf"] == [{"$ref": "#/$defs/Kind"}, {"type": "null"}]
    ts = reg.typescript()
    assert "export type Kind = 'x' | 'y';" in ts and "export const KINDS: readonly Kind[] = ['x', 'y'];" in ts
    assert "  inner: Inner;" in ts and "  many: Inner[];" in ts and "  maybe: Kind | null;" in ts
    assert "/** Inside. */\nexport type Inner = {" in ts


def test_an_alias_of_str_is_named_too():
    reg = make()
    Name = reg.alias("Name", str)

    @reg.shape
    class Box(TypedDict):
        v: Annotated[Name, F("a name")]

    assert reg.definition("Box")["properties"]["v"]["$ref"] == "#/$defs/Name"
    assert reg.definition("Name") == {"type": "string"}
    assert "export type Name = string;" in reg.typescript()


def test_an_alias_of_a_tuple_and_of_a_union_of_shapes():
    reg = make()
    Key = reg.alias("Key", tuple[str, str, str])

    @reg.shape
    class A(TypedDict):
        kind: Annotated[Literal["a"], F("tag")]

    @reg.shape
    class B(TypedDict):
        kind: Annotated[Literal["b"], F("tag")]
        n: Annotated[int, F("count")]

    Either = reg.alias("Either", A | B)

    @reg.shape
    class Box(TypedDict):
        key: Annotated[Key, F("a key")]
        either: Annotated[Either, F("one of two")]
        direct: Annotated[A | B | None, F("the same, spelled out")]

    assert reg.definition("Key")["prefixItems"] == [{"type": "string"}] * 3
    assert reg.definition("Either") == {"anyOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}]}
    assert reg.definition("Box")["properties"]["direct"]["anyOf"][0] == {"anyOf": [{"$ref": "#/$defs/A"},
                                                                                   {"$ref": "#/$defs/B"}]}
    ts = reg.typescript()
    assert "export type Key = [string, string, string];" in ts and "export type Either = A | B;" in ts
    assert "  direct: A | B | null;" in ts


def test_the_object_union_validates_a_value_of_one_variant_and_lists_the_first_ones_problems_otherwise():
    reg = make()

    @reg.shape
    class A(TypedDict):
        kind: Annotated[Literal["a"], F("tag")]

    @reg.shape
    class B(TypedDict):
        kind: Annotated[Literal["b"], F("tag")]
        n: Annotated[int, F("count")]

    Either = reg.alias("Either", A | B)
    assert reg.validate({"kind": "a"}, "Either") == []
    assert reg.validate({"kind": "b", "n": 1}, "Either") == []
    assert reg.validate({"kind": "c"}, "Either") == reg.validate({"kind": "c"}, "A") == [
        "$.kind: expected one of ['a'], got 'c'"]


def test_a_field_with_a_doc_and_shown_carries_them():
    reg = construct(int)
    p = reg.definition("Box")["properties"]["v"]
    assert (p["description"], p["x-shown"]) == ("the value", True)

    class Quiet(TypedDict):
        v: Annotated[int, F("hidden id", shown=False)]

    reg.shape(Quiet)
    assert reg.definition("Quiet")["properties"]["v"]["x-shown"] is False
    assert "  /** hidden id */\n  v: number;" in reg.typescript()


def test_a_shape_without_fields_is_the_empty_object():
    reg = make()

    @reg.shape
    class Empty(TypedDict):
        """Nothing."""

    assert reg.definition("Empty") == {"type": "object", "properties": {}, "additionalProperties": False,
                                       "description": "Nothing."}
    assert "export type Empty = Record<string, never>;" in reg.typescript()
    assert reg.validate({}, "Empty") == [] and reg.validate({"a": 1}, "Empty") == ["$.a: unexpected key"]


def test_json_schema_has_the_closure_and_the_dialect():
    reg = make()
    Kind = reg.alias("Kind", Literal["x"])

    @reg.shape
    class Inner(TypedDict):
        k: Annotated[Kind, F("k")]

    @reg.shape
    class Outer(TypedDict):
        i: Annotated[Inner, F("i")]

    @reg.shape
    class Alone(TypedDict):
        n: Annotated[int, F("n")]

    schema = reg.json_schema("Outer")
    assert schema["$ref"] == "#/$defs/Outer" and schema["$schema"].endswith("2020-12/schema")
    assert list(schema["$defs"]) == ["Kind", "Inner", "Outer"]
    assert reg.json_schema("Kind")["$defs"] == {"Kind": {"const": "x"}}
    assert list(reg.definitions()) == ["Kind", "Inner", "Outer", "Alone"]
    with pytest.raises(KeyError):
        reg.json_schema("Nope")


def test_long_docs_wrap_into_a_block_comment_and_a_comment_end_is_defused():
    reg = make()

    @reg.shape
    class Box(TypedDict):
        v: Annotated[int, F("word " * 40 + "end */")]

    ts = reg.typescript()
    assert "  /**\n   * word word" in ts and ts.count("*/") == 1 and "end * /" in ts


# --- refusals ---

def refused(build, *needles: str):
    with pytest.raises(ShapeError) as raised:
        build()
    assert isinstance(raised.value, TypeError)
    for needle in needles:
        assert needle in str(raised.value)


def test_a_field_without_f_is_refused_naming_class_and_field():
    reg = make()

    def build():
        @reg.shape
        class Bare(TypedDict):
            v: int

    refused(build, "Bare.v", "F")
    assert "Bare" not in reg.shapes


def test_two_fs_are_refused():
    reg = make()

    def build():
        @reg.shape
        class Twice(TypedDict):
            v: Annotated[int, F("a"), F("b")]

    refused(build, "Twice.v", "2")


@pytest.mark.parametrize("tp", [set[str], dict[int, str], list, tuple[int, ...], tuple, float | str, bytes,
                                Literal[1.5], dict, type(None)])
def test_an_unsupported_type_is_refused(tp):
    reg = make()

    def build():
        @reg.shape
        class Odd(TypedDict):
            v: Annotated[tp, F("odd")]

    refused(build, "Odd.v")


def test_a_plain_class_and_an_unregistered_shape_are_refused():
    reg = make()

    class Plain:
        pass

    class Loose(TypedDict):
        a: Annotated[int, F("a")]

    for tp in (Plain, Loose):
        def build(tp=tp):
            @reg.shape
            class Odd(TypedDict):
                v: Annotated[tp, F("odd")]

        refused(build, "Odd.v")


def test_a_union_of_unregistered_shapes_is_refused():
    reg = make()

    class A(TypedDict):
        a: Annotated[int, F("a")]

    class B(TypedDict):
        b: Annotated[int, F("b")]

    def build():
        @reg.shape
        class Odd(TypedDict):
            v: Annotated[A | B, F("odd")]

    refused(build, "Odd.v")


def test_a_duplicate_name_is_refused_for_shapes_and_aliases():
    reg = make()

    @reg.shape
    class Once(TypedDict):
        a: Annotated[int, F("a")]

    reg.alias("Word", str)

    def again():
        @reg.shape
        class Once(TypedDict):  # noqa: F811
            a: Annotated[int, F("a")]

    refused(again, "Once", "twice")
    refused(lambda: reg.alias("Word", int), "Word", "twice")
    refused(lambda: reg.alias("Once", int), "Once", "twice")


def test_an_alias_of_a_bad_type_or_a_const_of_a_non_literal_is_refused():
    reg = make()
    refused(lambda: reg.alias("Bad", set[str]), "Bad")
    refused(lambda: reg.alias("Names", str, const="NAMES"), "Names", "Literal")


def test_a_shape_must_be_a_typed_dict_and_its_base_registered():
    reg = make()
    refused(lambda: reg.shape(dict), "dict")

    class Base(TypedDict):
        a: Annotated[int, F("a")]

    def build():
        @reg.shape
        class Child(Base):
            b: Annotated[int, F("b")]

    refused(build, "Child", "Base")


# --- inheritance ---

def test_a_subclass_is_base_and_own_fields_in_typescript_and_flat_in_json():
    reg = make()

    @reg.shape
    class Base(TypedDict):
        """The base."""
        a: Annotated[int, F("a")]

    @reg.shape
    class Child(Base):
        """The child."""
        b: Annotated[str, F("b")]
        c: NotRequired[Annotated[bool, F("c")]]

    @reg.shape
    class Same(Base):
        pass

    ts = reg.typescript()
    assert "export type Child = Base & {\n  /** b */\n  b: string;\n  /** c */\n  c?: boolean;\n};" in ts
    assert "export type Same = Base;" in ts
    child = reg.definition("Child")
    assert list(child["properties"]) == ["a", "b", "c"] and child["required"] == ["a", "b"]
    assert child["additionalProperties"] is False and "allOf" not in child
    assert reg.validate({"a": 1, "b": "x"}, "Child") == []
    assert reg.validate({"a": 1}, "Child") == ["$.b: missing"]
    assert list(reg.json_schema("Child")["$defs"]) == ["Base", "Child"]


# --- validate ---

def sample() -> Registry:
    reg = make()
    Colour = reg.alias("Colour", Literal["red", "blue"])

    @reg.shape
    class Item(TypedDict):
        rev: Annotated[int, F("revision")]
        name: Annotated[str | None, F("name")]
        colour: Annotated[Colour, F("colour")]
        ok: Annotated[Literal[True], F("always")]
        note: NotRequired[Annotated[str, F("a note")]]

    @reg.shape
    class Group(TypedDict):
        items: Annotated[list[Item], F("the items")]
        pair: Annotated[tuple[str, int], F("a pair")]
        by: Annotated[dict[str, Item], F("by key")]
        free: Annotated[Any, F("anything")]

    return reg


def item(**over) -> dict:
    return {"rev": 1, "name": None, "colour": "red", "ok": True, **over}


def group(**over) -> dict:
    return {"items": [item()], "pair": ["a", 1], "by": {}, "free": object(), **over}


def test_a_valid_value_has_no_problems():
    reg = sample()
    assert reg.validate(item(), "Item") == []
    assert reg.validate(item(note="x"), "Item") == []
    assert reg.validate(group(pair=("a", 1), by={"k": item()}), "Group") == []


def test_each_kind_of_mismatch_is_one_problem_with_its_path():
    reg = sample()
    bad_item = {"rev": 1, "name": None, "colour": "red"}
    cases = [
        (group(items=[item(), item(), item(), {k: v for k, v in item().items() if k != "rev"}]),
         ["$.items[3].rev: missing"]),
        (group(items=[item(extra=1)]), ["$.items[0].extra: unexpected key"]),
        (group(items=[item(rev="1")]), ["$.items[0].rev: expected int, got str"]),
        (group(items=[item(rev=True)]), ["$.items[0].rev: expected int, got bool"]),
        (group(items=[item(colour="green")]), ["$.items[0].colour: expected one of ['red', 'blue'], got 'green'"]),
        (group(items=[item(ok=False)]), ["$.items[0].ok: expected one of [True], got False"]),
        (group(items=[item(ok=1)]), ["$.items[0].ok: expected one of [True], got 1"]),
        (group(items=[item(colour=None)]), ["$.items[0].colour: expected one of ['red', 'blue'], got None"]),
        (group(items=[item(note=None)]), ["$.items[0].note: expected str, got null"]),
        (group(pair=["a"]), ["$.pair: expected 2 items, got 1"]),
        (group(pair=["a", "b"]), ["$.pair[1]: expected int, got str"]),
        (group(by={"k": item(rev=None)}), ["$.by.k.rev: expected int, got null"]),
        (group(items={}), ["$.items: expected a list, got dict"]),
        (group(items=[3]), ["$.items[0]: expected an object (Item), got int"]),
    ]
    for value, problems in cases:
        assert reg.validate(value, "Group") == problems, value
    assert bad_item and reg.validate(bad_item, "Item") == ["$.ok: missing"]


def test_a_float_takes_an_int_and_an_int_takes_no_float():
    reg = make()

    @reg.shape
    class Num(TypedDict):
        f: Annotated[float, F("f")]
        i: Annotated[int, F("i")]

    assert reg.validate({"f": 3, "i": 3}, "Num") == []
    assert reg.validate({"f": 3.5, "i": 3.5}, "Num") == ["$.i: expected int, got float"]
    assert reg.validate({"f": True, "i": 3}, "Num") == ["$.f: expected float, got bool"]


def test_an_alias_can_be_checked_by_name():
    reg = sample()
    assert reg.validate("red", "Colour") == [] and reg.validate("x", "Colour")


# --- the product's own registry ---

def test_every_field_of_every_product_shape_has_exactly_one_f():
    from discjockey.hub import shapes

    assert shapes.SHAPES
    for name, cls in shapes.SHAPES.items():
        for key, hint in kernel.typing.get_type_hints(cls, include_extras=True).items():
            _, metas, _ = kernel._peel(hint)
            assert len([m for m in metas if isinstance(m, F)]) == 1, f"{name}.{key}"


# --- the generated files and the maps ---

def test_the_generated_files_are_fresh():
    from discjockey.hub import shapes

    for path, text in shapes.generated().items():
        assert path.exists() and path.read_text(encoding="utf-8") == text, (
            f"{path.name} is stale: run `uv run python -m discjockey.hub.shapes --export`")


def test_the_check_command_says_what_is_stale(tmp_path, monkeypatch, capsys):
    from discjockey.hub import shapes
    from discjockey.hub.shapes import __main__ as export

    assert export.main(["--check"]) == 0
    stale = tmp_path / "types.gen.ts"
    stale.write_text("old\n")
    monkeypatch.setattr(shapes, "generated", lambda: {stale: "new\n", tmp_path / "missing.json": "x\n"})
    assert export.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "types.gen.ts" in err and "missing.json" in err and "--export" in err
    assert export.main(["--export"]) == 0
    assert stale.read_text() == "new\n" and (tmp_path / "missing.json").read_text() == "x\n"


def test_the_schemas_file_holds_every_shape_and_the_maps():
    import json

    from discjockey.hub import shapes

    text = shapes.schemas_text()
    body = json.loads(text)
    assert text.endswith("\n") and text == json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert set(body["$defs"]) == set(shapes.SHAPES) | set(shapes.ALIASES)
    assert body["answers"] == shapes.ANSWERS and body["results"] == shapes.RESULTS


def test_every_mapped_name_is_a_shape_and_every_answered_method_exists():
    from discjockey.hub import shapes
    from discjockey.hub.api import CliApi, HubApi

    for name in [*shapes.ANSWERS.values(), *shapes.RESULTS.values()]:
        assert name in shapes.SHAPES, name
    methods = {m for cls in (HubApi, CliApi) for m in dir(cls) if getattr(getattr(cls, m), "is_bridge", False)
               or getattr(getattr(cls, m), "is_cli_first", False)}
    assert set(shapes.ANSWERS) <= methods


def test_a_key_mapped_in_two_modules_is_refused(monkeypatch):
    from types import SimpleNamespace

    from discjockey.hub import shapes

    twin = SimpleNamespace(ANSWERS={"freshness": "Freshness"}, RESULTS={})
    monkeypatch.setattr(shapes, "AREAS", (*shapes.AREAS, twin))
    with pytest.raises(ShapeError, match="freshness"):
        shapes._merged("ANSWERS")
    monkeypatch.setattr(shapes, "AREAS", (SimpleNamespace(ANSWERS={"x": "Nowhere"}, RESULTS={}),))
    with pytest.raises(ShapeError, match="Nowhere"):
        shapes._merged("ANSWERS")


def test_the_catalogue_entry_of_a_method_names_its_shape():
    from discjockey.hub import catalog, shapes

    freshness = [e for e in catalog.ENTRIES if e.method == "freshness"]
    assert freshness and all(e.schema == "Freshness" == shapes.ANSWERS["freshness"] for e in freshness)


# --- test mode (T6, real outputs) ---

@pytest.fixture
def checking(monkeypatch):
    """Check mode on with two methods mapped (a method and a job kind), and nothing left behind."""
    from discjockey.hub import shapes

    monkeypatch.setattr(shapes, "CHECKING", True)
    monkeypatch.setitem(shapes.ANSWERS, "probe", "Freshness")
    monkeypatch.setitem(shapes.RESULTS, "probe_job", "Freshness")
    shapes.take_mismatches()
    yield shapes
    shapes.take_mismatches()


def test_a_wrong_answer_of_a_mapped_method_is_recorded_and_fails_the_fixtures_check(checking):
    from discjockey.hub import api

    class Page:
        def _need_library(self):
            pass

        @api.bridge
        def probe(self):
            return {"scanned_at": 5}

    answer = Page().probe()
    assert answer == {"ok": True, "scanned_at": 5}  # the page still gets the answer
    assert checking.MISMATCHES == [("answer of probe", ["$.scanned_at: expected str, got int",
                                                        "$.read_at: missing"])]
    assert checking.take_mismatches() == [
        "answer of probe: $.scanned_at: expected str, got int; $.read_at: missing"]
    assert checking.take_mismatches() == []


def test_a_right_answer_a_job_start_and_a_none_result_record_nothing(checking):
    from discjockey.hub import api

    class Page:
        def _need_library(self):
            pass

        @api.bridge
        def probe(self):
            return {"scanned_at": None, "read_at": "2026-11-20T10:00:00"}

    assert Page().probe()["ok"] is True
    checking.note_answer("probe", {"job_id": "job:00000001"})  # a J method's start: its result is checked instead
    checking.note_result("probe_job", None)
    checking.note_answer("unmapped", {"anything": 1})
    checking.note_result("unmapped_job", {"anything": 1})
    assert checking.MISMATCHES == []


def test_a_wrong_job_result_is_recorded_by_the_registry_when_an_ok_job_finishes(checking, tmp_path):
    from discjockey.hub.jobs import Jobs
    from discjockey.library import Paths

    paths = Paths(tmp_path, support=tmp_path / ".support")
    paths.data.mkdir()
    js = Jobs(paths.lock, lambda event: None)
    assert js.start("probe_job", lambda ctx: {"scanned_at": None, "read_at": None, "x": 1}).done.wait(5)
    assert checking.take_mismatches() == ["result of job probe_job: $.x: unexpected key"]
    assert js.start("probe_job", lambda ctx: None).done.wait(5)  # an ok job with no result
    assert checking.MISMATCHES == []


def test_with_checking_off_nothing_is_recorded(checking, monkeypatch):
    monkeypatch.setattr(checking, "CHECKING", False)
    checking.note_answer("probe", {"scanned_at": 5})
    checking.note_result("probe_job", {"nope": 1})
    assert checking.MISMATCHES == []


def test_a_check_never_raises_from_product_code(checking, monkeypatch):
    def broken(value, name):
        raise RuntimeError("boom")

    monkeypatch.setattr(checking, "validate", broken)
    checking.note_answer("probe", {"scanned_at": None, "read_at": None})
    checking.note_result("probe_job", {})
    assert [w for w, _ in checking.MISMATCHES] == ["answer of probe", "result of job probe_job"]
    assert all("boom" in p for _, ps in checking.MISMATCHES for p in ps)
    monkeypatch.setattr(checking, "ANSWERS", None)  # even a broken map
    checking.note_answer("probe", {})


@pytest.mark.shapes_unchecked
def test_a_test_marked_shapes_unchecked_is_not_failed_for_its_mismatches(checking):
    checking.note_answer("probe", {"scanned_at": 5})
    assert checking.MISMATCHES  # the autouse fixture finds it and lets it pass


def test_the_suite_runs_with_the_check_on():
    from discjockey.hub import shapes

    assert shapes.CHECKING  # tests/conftest.py sets DISCJOCKEY_CHECK_SHAPES before any discjockey import


# --- To-do, the details of a song and Missing files (E7b): a fixture answer fits its shape ---

@pytest.fixture
def hub(tmp_path, monkeypatch):
    from hub_helpers import fake_spotify, make_api, make_root

    fake_spotify(monkeypatch)
    api, _ = make_api(make_root(tmp_path, upgrade=True))
    return api


def answer_without_ok(answer: dict) -> dict:
    assert answer["ok"] is True, answer
    return {k: v for k, v in answer.items() if k != "ok"}


def test_a_todo_answer_fits_its_shape(hub):
    from discjockey.hub import shapes

    out = answer_without_ok(hub.todo())
    assert [g["key"] for g in out["groups"]] == ["upgrade_ready", "not_found"]  # a parked upgrade and a missing song
    assert shapes.validate(out, shapes.ANSWERS["todo"]) == []
    broken = {**out, "groups": [{**out["groups"][0], "key": "nowhere"}]}
    assert shapes.validate(broken, "Todo")  # the check can fail: the key is no group's


def test_a_track_answer_fits_its_shape(hub):
    from discjockey.hub import shapes

    for key in ("t1", "t2", "t3"):  # a lossless file, one with a parked upgrade, one nobody found
        assert shapes.validate(answer_without_ok(hub.track(key)), shapes.ANSWERS["track"]) == [], key
    assert hub.track("t2")["track"]["upgrade"]["swap_how"] in ("in_place", "new_aiff")


def test_a_missing_files_preview_answer_fits_its_shape(tmp_path, monkeypatch):
    from hub_helpers import LOSSLESS, fake_spotify, make_api, make_root

    from discjockey import db
    from discjockey.hub import shapes

    fake_spotify(monkeypatch)
    paths = make_root(tmp_path, upgrade=True)
    with db.connect(paths.db_file) as conn:
        conn.execute("UPDATE files SET missing_since = ? WHERE path = ?", ("2026-11-01", LOSSLESS.removeprefix("Library/")))
        conn.commit()
    api, _ = make_api(paths)
    for action in ("download_again", "remove"):
        out = answer_without_ok(api.missing_files_preview(["t1", "t2", "nope"], action))
        assert shapes.validate(out, shapes.ANSWERS["missing_files_preview"]) == [], action
        assert [i["track_id"] for i in out["items"]] == ["t1", "t2", "nope"]
        assert out["items"][0]["since"] == "2026-11-01" and out["items"][2]["reason"] == "not_missing"


# --- the dashboard, the sidebar, the Library, the Sync preview, the job snapshot and Download limits (E7c) ---

@pytest.fixture
def read_hub(tmp_path, monkeypatch):
    """A hub whose playlists were read (a plan with two new songs, a parked upgrade, a song nobody found)."""
    from hub_helpers import fake_spotify, make_api, make_root, refreshed

    fake_spotify(monkeypatch)
    api, rec = make_api(make_root(tmp_path, upgrade=True))
    return api, rec, lambda: refreshed(api, rec)


def fits(method: str, answer: dict) -> dict:
    from discjockey.hub import shapes

    out = answer_without_ok(answer)
    assert shapes.validate(out, shapes.ANSWERS[method]) == [], method
    return out


def test_a_dashboard_answer_fits_its_shape_before_and_after_the_read(read_hub):
    from discjockey.hub import shapes

    api, _, read = read_hub
    before = fits("dashboard", api.dashboard())
    assert before["ready"] is None and before["next_checks"] is None and before["tiles"]["still_to_load"]["count"] is None
    read()
    after = fits("dashboard", api.dashboard())
    assert after["ready"]["counts"]["new"] == 2 and after["tiles"]["still_to_load"]["count"] == 2
    broken = {**after, "tiles": {**after["tiles"], "qobuz_today": {**after["tiles"]["qobuz_today"], "used": "0"}}}
    assert shapes.validate(broken, "Dashboard")  # the check can fail


def test_a_sidebar_answer_fits_its_shape(read_hub):
    api, _, read = read_hub
    fits("sidebar", api.sidebar())
    read()
    out = fits("sidebar", api.sidebar())
    assert [p["name"] for p in out["playlists"]] == ["Hard_Bounce", "Powertrance"]


def test_a_library_answer_fits_its_shape_in_every_kind_of_view(read_hub):
    api, _, read = read_hub
    read()
    everything = fits("library", api.library())
    assert {r["file_state"] for r in everything["rows"]} <= {"here", "no_file"}
    playlist = fits("library", api.library("playlist", "Hard_Bounce"))
    assert playlist["songs"] is not None and any(r["file_state"] == "no_file" for r in playlist["rows"])
    fits("library", api.library("unlisted"))
    gone = fits("library", api.library("playlist", "No_Such_List"))
    assert gone["empty"] == "gone" and gone["rows"] == []


def test_a_sync_preview_answer_fits_its_shape_before_and_after_the_read(read_hub):
    from discjockey.hub import shapes

    api, _, read = read_hub
    assert fits("sync_preview", api.sync_preview())["empty"] == "no_preview"
    read()
    out = fits("sync_preview", api.sync_preview())
    assert [g["key"] for g in out["groups"]] == ["acquire:new"] and out["estimate"]["accounts"][0]["uses_by_downloads"]
    assert all(len(a["key"]) == 3 and "in" in a and "run" in a for a in out["groups"][0]["actions"])
    wrong = {**out, "groups": [{**out["groups"][0], "key": "move"}]}
    assert shapes.validate(wrong, "SyncPreview")  # there is no `move` group any more


def test_a_job_status_answer_fits_its_shape_idle_and_with_a_finished_job(read_hub):
    api, _, read = read_hub
    idle = fits("job_status", api.job_status())
    assert idle["job"] is None
    read()
    done = fits("job_status", api.job_status())
    assert done["job"] is None or done["job"]["kind"] == "refresh"


def test_a_limits_answer_fits_its_shape_for_every_service(read_hub):
    api, _, read = read_hub
    read()
    out = fits("limits", api.limits())
    assert [c["service"] for c in out["cards"]] == ["qobuz", "youtube", "soundcloud"] and out["usage"] is not None
    assert len(out["usage"]["days"]) == 14 and set(out["usage"]["signal_summary"]) >= {"login_failed", "auto_stop"}
    for service in ("youtube", "soundcloud"):
        assert fits("limits", api.limits(service))["usage"] is None  # not set up: only the cards
    fits("limits_what_if", api.limits_what_if("qobuz", 90, 20))
