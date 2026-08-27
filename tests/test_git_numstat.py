import pytest

from ai_commit_generator.git_errors import MalformedGitOutputError
from ai_commit_generator.git_numstat import FileTypeClassifier, GitNumstatParser


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("folder/file.PY", "py"),
        ("folder/archive.tar.GZ", "gz"),
        ("README", "extensionless"),
        (".gitignore", "extensionless"),
        ("folder/name.", "extensionless"),
        ("folder/naïve.MD", "md"),
        ("folder/a b\tc\nname.MD", "md"),
    ],
)
def test_classifies_unusual_paths(path: str, expected: str) -> None:
    assert FileTypeClassifier().classify(path) == expected


def test_parses_binary_deleted_and_gitlink_records() -> None:
    analysis = GitNumstatParser().parse(
        "\0".join(
            (
                "-\t-\timage.PNG",
                "0\t12\tdeleted.py",
                "1\t1\tvendor/library",
                "",
            )
        )
    )

    assert analysis.as_dict() == {
        "files_changed": 3,
        "insertions": 1,
        "deletions": 13,
        "file_types": ["extensionless", "png", "py"],
    }


def test_parses_rename_with_unusual_destination() -> None:
    analysis = GitNumstatParser().parse("0\t0\t\0old name.md\0new\tname\n.PY\0")

    assert analysis.files_changed == 1
    assert analysis.file_types == ("py",)


@pytest.mark.parametrize("output", ["", "\0", "\0\0\0"])
def test_empty_and_extra_nul_separators_return_zero_analysis(output: str) -> None:
    assert GitNumstatParser().parse(output).files_changed == 0


@pytest.mark.parametrize(
    ("output", "message"),
    [
        ("malformed\0", "malformed"),
        ("one\t2\tfile.py\0", "non-numeric"),
        ("-1\t2\tfile.py\0", "negative"),
        ("-\t2\tfile.py\0", "inconsistent binary"),
        ("1\t2\tfile.py", "not NUL-terminated"),
        ("1\t2\t\0old.py\0", "incomplete rename"),
        ("1\t2\t\0\0new.py\0", "incomplete rename"),
    ],
)
def test_rejects_malformed_records(output: str, message: str) -> None:
    with pytest.raises(MalformedGitOutputError, match=message):
        GitNumstatParser().parse(output)
