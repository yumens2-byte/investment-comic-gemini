from scripts.check_branch_update_ready import collect_status, format_status


def _runner(outputs):
    def run(args):
        key = tuple(args)
        value = outputs.get(key, (1, "", ""))
        if isinstance(value, str):
            return 0, value, ""
        return value

    return run


def test_collect_status_blocks_without_remote_or_upstream() -> None:
    status = collect_status(
        _runner(
            {
                ("branch", "--show-current"): "work",
                ("rev-parse", "HEAD"): "abc123",
                ("remote",): "",
                ("status", "--porcelain=v1"): "",
            }
        )
    )

    assert not status.ready
    assert status.remotes == ()
    assert any("remote" in problem for problem in status.problems)


def test_collect_status_ready_with_remote_upstream_and_clean_tree() -> None:
    status = collect_status(
        _runner(
            {
                ("branch", "--show-current"): "main",
                ("rev-parse", "HEAD"): "abc123",
                ("remote",): "origin",
                ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): "origin/main",
                ("status", "--porcelain=v1"): "",
            }
        )
    )

    assert status.ready
    assert status.upstream == "origin/main"
    assert "result: OK" in format_status(status)


def test_collect_status_reports_dirty_worktree() -> None:
    status = collect_status(
        _runner(
            {
                ("branch", "--show-current"): "main",
                ("rev-parse", "HEAD"): "abc123",
                ("remote",): "origin",
                ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): "origin/main",
                ("status", "--porcelain=v1"): " M file.py",
            }
        )
    )

    assert not status.ready
    assert status.dirty_files == (" M file.py",)
    assert any("변경사항" in problem for problem in status.problems)
