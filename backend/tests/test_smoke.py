from backend import main


def test_main_runs(capsys) -> None:
    main()
    captured = capsys.readouterr()
    assert captured.out == "Hello from backend!\n"
