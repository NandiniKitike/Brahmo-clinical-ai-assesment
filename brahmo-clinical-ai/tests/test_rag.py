import pytest
from unittest.mock import patch, MagicMock
from app.rag.answerer import generate_answer
from app.models import CorpusChunk

@patch("app.rag.answerer.genai.GenerativeModel")
def test_generate_answer(mock_model):
    mock_instance = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "According to the clinic's own protocol, paracetamol is recommended. [local_protocol_acute_fever.md, Page 1]"
    mock_instance.generate_content.return_value = mock_response
    mock_model.return_value = mock_instance
    
    mock_chunk = CorpusChunk(
        id="chunk-1",
        source_file="local_protocol_acute_fever.md",
        page_anchor="Page 1",
        specialty="General",
        condition="Fever",
        content="Paracetamol is recommended.",
        is_local_protocol=True
    )
    
    answer, citations = generate_answer("What is recommended for fever?", [mock_chunk])
    
    assert "paracetamol is recommended" in answer.lower()
    assert citations[0]["source_file"] == "local_protocol_acute_fever.md"
    assert citations[0]["is_local_protocol"] is True

def test_generate_answer_no_chunks():
    answer, citations = generate_answer("What is the dose?", [])
    assert "cannot answer" in answer.lower()
    assert len(citations) == 0
