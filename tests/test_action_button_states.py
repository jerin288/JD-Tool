from app.views.main_window import calculate_action_button_states


def test_requested_valid_with_unmatched_suspense_scenario_enables_all_actions() -> None:
    states = calculate_action_button_states(
        transaction_count=18,
        critical_error_count=0,
        tally_connected=True,
        bank_ledger_selected=True,
    )

    assert states.preview_enabled is True
    assert states.export_enabled is True
    assert states.tally_enabled is True


def test_preview_is_independent_of_errors_and_tally_connection() -> None:
    states = calculate_action_button_states(
        transaction_count=4,
        critical_error_count=2,
        tally_connected=False,
        bank_ledger_selected=False,
    )

    assert states.preview_enabled is True
    assert states.export_enabled is False
    assert states.tally_enabled is False


def test_export_does_not_require_tally_but_send_does() -> None:
    states = calculate_action_button_states(
        transaction_count=4,
        critical_error_count=0,
        tally_connected=False,
        bank_ledger_selected=True,
    )

    assert states.preview_enabled is True
    assert states.export_enabled is True
    assert states.tally_enabled is False
