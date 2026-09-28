import asyncio
import subprocess

from chumai import updater


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"], "HOME": str(cwd)})


def test_check_pulls_and_explains_failures(tmp_path, monkeypatch):
    origin, work, clone = tmp_path / "origin.git", tmp_path / "work", tmp_path / "clone"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    (work / "a.txt").write_text("1")
    _git(work, "add", ".")
    _git(work, "commit", "-qm", "one")
    _git(work, "push", "-q", "origin", "HEAD")
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    monkeypatch.setattr(updater, "REPO", clone)

    pulled, msg = asyncio.run(updater.check())
    assert not pulled and "이미 최신" in msg

    (work / "a.txt").write_text("2")
    _git(work, "commit", "-qam", "two")
    _git(work, "push", "-q", "origin", "HEAD")
    (clone / "a.txt").write_text("edited locally")  # blocks a fast-forward pull
    pulled, msg = asyncio.run(updater.check())
    assert not pulled and "받지 못했어요" in msg and "git status" in msg

    _git(clone, "checkout", "--", "a.txt")
    pulled, msg = asyncio.run(updater.check())
    assert pulled and "업데이트했어요" in msg and (clone / "a.txt").read_text() == "2"
    assert asyncio.run(updater.version()) != "?"
