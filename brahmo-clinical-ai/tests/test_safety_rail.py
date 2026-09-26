import pytest
from unittest.mock import MagicMock
from app.drug_master.safety_rail import SafetyRail, PrescriptionItem, RailResult
from app.models import CheckState, CheckSeverity

def test_resolve_product_exact_match():
    # Mock DB session
    mock_db = MagicMock()
    # Setup mock product
    mock_product = MagicMock()
    mock_product.id = "prod-123"
    mock_product.brand_name = "Dolo 650"
    
    # Mock query.filter().first() to return mock_product
    mock_db.query().filter().first.return_value = mock_product
    
    rail = SafetyRail(mock_db)
    item = rail.resolve_product("Dolo 650")
    
    assert item.resolved is True
    assert item.product_id == "prod-123"
    assert item.resolution_confidence == 1.0

def test_duplicate_ingredient_check():
    mock_db = MagicMock()
    rail = SafetyRail(mock_db)
    
    # Setup mock ingredients (duplicate paracetamol)
    mock_item1 = PrescriptionItem("Dolo 650", resolved=True, product_id="p1", doses_per_day=3)
    mock_prod1 = MagicMock()
    mock_prod1.id = "p1"
    mock_prod1.brand_name = "Dolo 650"
    mock_ing1 = MagicMock()
    mock_ing1.name = "Paracetamol"
    mock_comp1 = MagicMock()
    mock_comp1.strength_value = 650
    
    mock_item2 = PrescriptionItem("Sinarest", resolved=True, product_id="p2", doses_per_day=2)
    mock_prod2 = MagicMock()
    mock_prod2.id = "p2"
    mock_prod2.brand_name = "Sinarest"
    mock_ing2 = MagicMock()
    mock_ing2.name = "Paracetamol"
    mock_comp2 = MagicMock()
    mock_comp2.strength_value = 500
    
    resolved_items = [
        (mock_item1, mock_prod1, [(mock_ing1, mock_comp1)]),
        (mock_item2, mock_prod2, [(mock_ing2, mock_comp2)])
    ]
    
    result = rail.check_duplicate_ingredient(resolved_items)
    
    assert result.check_state == CheckState.HIT
    assert result.severity == CheckSeverity.HIGH
    assert "Paracetamol" in result.evidence
    
def test_interaction_no_hit():
    mock_db = MagicMock()
    # Mock no interactions found
    mock_db.query().filter().all.return_value = []
    
    rail = SafetyRail(mock_db)
    
    mock_item = PrescriptionItem("Aspirin", resolved=True)
    mock_prod = MagicMock()
    mock_ing = MagicMock()
    mock_ing.id = "ing-1"
    
    resolved_items = [
        (mock_item, mock_prod, [(mock_ing, MagicMock())]),
        (mock_item, mock_prod, [(MagicMock(id="ing-2"), MagicMock())])
    ]
    
    result = rail.check_interactions(resolved_items)
    assert result.check_state == CheckState.CHECKED_NO_HIT
