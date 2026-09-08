from app.rag.loader import load_corpus


def test_loads_every_markdown_file(tmp_path):
    (tmp_path / "a.md").write_text("# Doc A\n\nSome content about A.")
    (tmp_path / "b.md").write_text("# Doc B\n\nSome content about B.")
    (tmp_path / "notes.txt").write_text("should be ignored, not markdown")

    documents = load_corpus(tmp_path)

    assert len(documents) == 2
    assert {d.metadata["source_id"] for d in documents} == {"a", "b"}


def test_sets_source_id_from_filename_stem(tmp_path):
    (tmp_path / "return_policy.md").write_text("# Return Policy\n\nDetails here.")

    [document] = load_corpus(tmp_path)

    assert document.metadata["source_id"] == "return_policy"


def test_sets_title_from_first_line(tmp_path):
    (tmp_path / "a.md").write_text("# Warranty Policy\n\nElectronics get a 1-year warranty.")

    [document] = load_corpus(tmp_path)

    assert document.metadata["title"] == "Warranty Policy"
    assert "Electronics get a 1-year warranty." in document.page_content


def test_empty_directory_returns_no_documents(tmp_path):
    assert load_corpus(tmp_path) == []
