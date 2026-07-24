from fabpublisher.shipfilter import ShipFilter


def test_default_excludes_build_artifacts():
    f = ShipFilter()
    assert f.should_exclude("Binaries/Win64/x.dll")
    assert f.should_exclude("Intermediate/Build/y.obj")
    assert f.should_exclude("Saved/log.txt")
    assert not f.should_exclude("Source/Module/Module.cpp")


def test_extension_glob_any_depth():
    f = ShipFilter(["*.md"])
    assert f.should_exclude("README.md")
    assert f.should_exclude("Docs/Guide/Intro.md")
    assert not f.should_exclude("Source/x.cpp")


def test_directory_pattern():
    f = ShipFilter(["Docs/"])
    assert f.should_exclude("Docs/x.txt")
    assert f.should_exclude("Sub/Docs/y.txt")
    assert not f.should_exclude("Documentation/z.txt")


def test_path_glob():
    f = ShipFilter(["Source/*/Private/*.cpp"])
    assert f.should_exclude("Source/Mod/Private/a.cpp")
    assert not f.should_exclude("Source/Mod/Public/a.cpp")


def test_pdb_and_dotfiles():
    f = ShipFilter(["*.pdb", ".DS_Store"])
    assert f.should_exclude("Binaries/x.pdb") is True  # also covered by default
    assert f.should_exclude("Content/.DS_Store")


def test_blank_and_comment_lines_ignored():
    f = ShipFilter(["", "  ", "# a comment", "*.tmp"])
    assert f.should_exclude("x.tmp")
    assert not f.should_exclude("x.cpp")
