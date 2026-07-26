"""Tests for the Qt-free Application layer (application/app.py).

Covers every workflow that used to require manual QA through the Qt
widgets: new project, task/resource/assignment CRUD, predecessor edits
(including invalid/cyclic rollback), settings changes, baselines,
undo/redo, save/load, and projection recomputation.
"""

from datetime import date

import pytest

from coconut.application.app import Application
from coconut.core.exceptions import NothingToRedoError, NothingToUndoError, ValidationError
from coconut.core.models import ConstraintType

PROJECT_START = date(2026, 1, 1)


@pytest.fixture
def app():
    application = Application()
    application.new_project(name="Test Project", start=PROJECT_START)
    return application


def test_new_project_resets_state(app):
    app.add_task("A", 3)
    app.new_project(name="Fresh", start=date(2026, 3, 1))

    assert app.project.name == "Fresh"
    assert app.project.tasks == []
    assert app.current_path is None
    assert app.is_dirty is False
    assert app.can_undo is False
    assert app.can_redo is False


def test_add_task_marks_dirty_and_updates_projection(app):
    assert app.is_dirty is False
    task_id = app.add_task("Design", 5)

    assert app.is_dirty is True
    assert [row.task_id for row in app.projections.task_rows] == [task_id]
    assert app.projections.task_rows[0].name == "Design"
    assert app.projections.task_rows[0].duration_days == 5


def test_edit_task_duration_updates_projection(app):
    task_id = app.add_task("Design", 5)
    app.edit_task_duration(task_id, 8)

    assert app.projections.task_rows[0].duration_days == 8
    assert app.projections.gantt.bars[0].task_id == task_id


def test_add_task_defaults_to_red(app):
    task_id = app.add_task("Design", 5)
    assert app.projections.task_rows[0].color_id == "red"
    assert app.projections.gantt.bars[0].color_id == "red"


def test_edit_task_color_updates_projection_and_inherits_to_children(app):
    parent_id = app.add_task("Phase", 5)
    child_id = app.add_task("Sub-task", 2)
    app.indent_task(child_id)

    app.edit_task_color(parent_id, "peach")

    rows_by_id = {row.task_id: row for row in app.projections.task_rows}
    assert rows_by_id[parent_id].color_id == "peach"
    assert rows_by_id[child_id].color_id == "peach"
    bars_by_id = {bar.task_id: bar for bar in app.projections.gantt.bars}
    assert bars_by_id[parent_id].color_id == "peach"
    assert bars_by_id[parent_id].is_top_level is True
    assert bars_by_id[child_id].color_id == "peach"
    assert bars_by_id[child_id].is_top_level is False

    app.undo()
    assert app.projections.task_rows[0].color_id == "red"


def test_remove_task_updates_projection(app):
    task_id = app.add_task("Design", 5)
    app.remove_task(task_id)

    assert app.projections.task_rows == ()
    assert app.projections.gantt.row_count == 0


def test_reorder_task_updates_row_positions(app):
    first = app.add_task("A", 1)
    second = app.add_task("B", 1)

    app.move_task(first, 1)

    rows = {row.task_id: row.row for row in app.projections.task_rows}
    assert rows[second] == 0
    assert rows[first] == 1


def test_edit_task_progress(app):
    task_id = app.add_task("A", 5)
    app.edit_task_progress(task_id, 50.0, actual_start=PROJECT_START)

    row = app.projections.task_rows[0]
    assert row.percent_complete == 50.0
    assert row.actual_start == PROJECT_START


def test_set_predecessors_from_text(app):
    app.add_task("A", 3)
    second_id = app.add_task("B", 2)

    app.set_predecessors_from_text(second_id, "1")

    row = next(r for r in app.projections.task_rows if r.task_id == second_id)
    assert row.predecessors_text == "1"


def test_set_predecessors_accepts_nested_wbs_ids(app):
    app.add_task("Phase 1", 1)
    nested_id = app.add_task("Nested predecessor", 3)
    successor_id = app.add_task("Successor", 2)
    app.indent_task(nested_id)

    app.set_predecessors_from_text(successor_id, "1.1FS+2")

    dep = app.project.get_dependency(nested_id, successor_id)
    assert dep.lag_days == 2
    row = next(r for r in app.projections.task_rows if r.task_id == successor_id)
    assert row.predecessors_text == "1.1FS+2"


def test_predecessor_display_updates_to_current_wbs_id(app):
    first_id = app.add_task("Phase 1", 1)
    nested_id = app.add_task("Nested predecessor", 3)
    successor_id = app.add_task("Successor", 2)
    app.indent_task(nested_id)
    app.set_predecessors_from_text(successor_id, "1.1")

    app.outdent_task(nested_id)

    row = next(r for r in app.projections.task_rows if r.task_id == successor_id)
    assert app.project.get_dependency(nested_id, successor_id)
    assert row.predecessors_text == "2"
    assert next(r for r in app.projections.task_rows if r.task_id == first_id).outline_number == "1"


def test_set_predecessors_invalid_text_raises_and_does_not_mutate(app):
    app.add_task("A", 3)
    second_id = app.add_task("B", 2)

    with pytest.raises(ValidationError):
        app.set_predecessors_from_text(second_id, "not-a-term")

    row = next(r for r in app.projections.task_rows if r.task_id == second_id)
    assert row.predecessors_text == ""


def test_set_predecessors_cyclic_rolls_back(app):
    first_id = app.add_task("A", 3)
    second_id = app.add_task("B", 2)

    app.set_predecessors_from_text(second_id, "1")  # B depends on A
    assert app.can_undo is True
    undo_depth_before = len(app._undo_stack)

    with pytest.raises(ValidationError):
        # A depends on B would create a cycle (A -> B already exists via row 1).
        app.set_predecessors_from_text(first_id, "2")

    # Rollback restores state and undo stack depth exactly.
    assert len(app._undo_stack) == undo_depth_before
    row_a = next(r for r in app.projections.task_rows if r.task_id == first_id)
    assert row_a.predecessors_text == ""


def test_add_and_remove_resource(app):
    resource_id = app.add_resource("Alice", rate=50.0, max_units=1.0)
    assert [r.resource_id for r in app.projections.resource_rows] == [resource_id]

    app.remove_resource(resource_id)
    assert app.projections.resource_rows == ()


def test_add_and_remove_assignment(app):
    task_id = app.add_task("A", 5)
    resource_id = app.add_resource("Alice", rate=50.0, max_units=1.0)

    app.add_assignment(task_id, resource_id, units=1.0)
    assert [a.resource_id for a in app.assignment_rows(task_id)] == [resource_id]
    assert app.assignable_resources(task_id) == []

    app.remove_assignment(task_id, resource_id)
    assert app.assignment_rows(task_id) == []
    assert [r.resource_id for r in app.assignable_resources(task_id)] == [resource_id]


def test_assignment_over_allocation_reflected_in_projection(app):
    task_a = app.add_task("A", 5)
    task_b = app.add_task("B", 5)
    resource_id = app.add_resource("Alice", rate=50.0, max_units=1.0)

    app.add_assignment(task_a, resource_id, units=1.0)
    app.add_assignment(task_b, resource_id, units=1.0)

    resource_row = app.projections.resource_rows[0]
    assert resource_row.is_over_allocated is True


def test_project_settings_change(app):
    new_start = date(2026, 2, 1)
    app.add_task("A", 3)
    app.set_project_settings(start=new_start, working_weekdays=frozenset({0, 1, 2, 3, 4, 5}))

    assert app.project.start == new_start
    assert app.project.calendar.working_weekdays == frozenset({0, 1, 2, 3, 4, 5})
    assert app.projections.gantt.bars[0].start == new_start


def test_capture_baseline_and_select(app):
    task_id = app.add_task("A", 3)
    baseline_id = app.capture_baseline("Baseline 1")

    assert [b.baseline_id for b in app.projections.baseline_list] == [baseline_id]

    app.select_baseline(baseline_id)
    variances = app.variance_rows(baseline_id)
    assert len(variances) == 1
    assert variances[0].task_id == task_id
    assert app.projections.gantt.baseline_bars[0].task_id == task_id


def test_undo_redo_across_intents(app):
    task_id = app.add_task("A", 3)
    app.edit_task_duration(task_id, 9)
    assert app.projections.task_rows[0].duration_days == 9

    app.undo()
    assert app.projections.task_rows[0].duration_days == 3

    app.undo()
    assert app.projections.task_rows == ()

    app.redo()
    assert app.projections.task_rows[0].duration_days == 3

    app.redo()
    assert app.projections.task_rows[0].duration_days == 9


def test_undo_with_empty_stack_raises(app):
    with pytest.raises(NothingToUndoError):
        app.undo()


def test_redo_with_empty_stack_raises(app):
    with pytest.raises(NothingToRedoError):
        app.redo()


def test_new_command_clears_redo_stack(app):
    task_id = app.add_task("A", 3)
    app.undo()
    app.add_task("B", 1)

    with pytest.raises(NothingToRedoError):
        app.redo()


def test_save_and_load_round_trip(tmp_path, app):
    app.add_task("A", 3)
    app.add_resource("Alice", rate=25.0, max_units=1.0)
    path = str(tmp_path / "test.coco")

    app.save_project(path)
    assert app.current_path == path
    assert app.is_dirty is False

    reopened = Application()
    reopened.open_project(path)

    assert reopened.project.name == app.project.name
    assert [t.name for t in reopened.project.tasks] == ["A"]
    assert reopened.is_dirty is False
    assert reopened.can_undo is False


def test_save_without_path_or_current_path_raises(app):
    with pytest.raises(ValidationError):
        app.save_project()


def test_save_marks_clean(app):
    app.add_task("A", 3)
    assert app.is_dirty is True
    # not writing to disk in this test beyond what's needed


# -- WBS hierarchy (Phase 7) -------------------------------------------


def test_flat_project_task_rows_have_top_level_outline_numbers(app):
    first = app.add_task("A", 3)
    second = app.add_task("B", 2)

    rows = {r.task_id: r for r in app.projections.task_rows}
    assert rows[first].outline_number == "1"
    assert rows[second].outline_number == "2"
    assert rows[first].depth == 0
    assert rows[first].is_summary is False
    assert rows[first].can_indent is False
    assert rows[second].can_indent is True


def test_indent_task_creates_summary_parent(app):
    first = app.add_task("A", 3)
    second = app.add_task("B", 2)

    app.indent_task(second)

    rows = {r.task_id: r for r in app.projections.task_rows}
    assert rows[first].is_summary is True
    assert rows[second].depth == 1
    assert rows[first].outline_number == "1"
    assert rows[second].outline_number == "1.1"


def test_moving_indented_task_down_reparents_to_new_preceding_parent(app):
    first = app.add_task("A", 3)
    second = app.add_task("B", 2)
    third = app.add_task("C", 1)
    app.indent_task(second)

    app.move_task(second, 2)

    rows = {r.task_id: r for r in app.projections.task_rows}
    assert app.project.get_task(second).parent_id == third
    assert rows[first].outline_number == "1"
    assert rows[third].outline_number == "2"
    assert rows[second].outline_number == "2.1"


def test_moving_indented_task_before_parent_outdents_and_undo_restores(app):
    first = app.add_task("A", 3)
    second = app.add_task("B", 2)
    app.indent_task(second)

    app.move_task(second, 0)

    rows = {r.task_id: r for r in app.projections.task_rows}
    assert app.project.get_task(second).parent_id is None
    assert rows[second].outline_number == "1"
    assert rows[first].outline_number == "2"

    app.undo()

    rows = {r.task_id: r for r in app.projections.task_rows}
    assert app.project.get_task(second).parent_id == first
    assert rows[first].outline_number == "1"
    assert rows[second].outline_number == "1.1"


def test_indent_first_task_raises(app):
    first = app.add_task("A", 3)

    with pytest.raises(ValidationError):
        app.indent_task(first)


def test_outdent_task_restores_top_level(app):
    first = app.add_task("A", 3)
    second = app.add_task("B", 2)
    app.indent_task(second)

    app.outdent_task(second)

    rows = {r.task_id: r for r in app.projections.task_rows}
    assert rows[second].depth == 0
    assert rows[first].is_summary is False


def test_outdent_top_level_task_raises(app):
    first = app.add_task("A", 3)

    with pytest.raises(ValidationError):
        app.outdent_task(first)


def test_indent_outdent_are_undoable(app):
    first = app.add_task("A", 3)
    second = app.add_task("B", 2)

    app.indent_task(second)
    assert app.projections.task_rows[1].depth == 1

    app.undo()
    assert app.projections.task_rows[1].depth == 0

    app.redo()
    assert app.projections.task_rows[1].depth == 1


def test_summary_task_rollup_dates_duration_and_percent(app):
    first = app.add_task("A", 3)
    second = app.add_task("B", 2)
    app.indent_task(second)
    third = app.add_task("C", 4)
    app.move_task(third, 1)
    app.indent_task(third)
    app.edit_task_progress(second, 0.0)
    app.edit_task_progress(third, 100.0)

    rows = {r.task_id: r for r in app.projections.task_rows}
    parent_row = rows[first]

    # A summary task's own duration/% fields are ignored once it has
    # children Ã¢â‚¬â€ only leaf descendants (here, B and C) feed the rollup:
    # duration-weighted % complete is (0*2 + 100*4) / (2+4) = ~66.67.
    assert parent_row.is_summary is True
    assert parent_row.percent_complete == pytest.approx(400.0 / 6.0)
    assert parent_row.duration_days == pytest.approx(6)

    bars = {b.task_id: b for b in app.projections.gantt.bars}
    assert bars[first].start == bars[second].start
    assert bars[first].finish == bars[third].finish


def test_summary_row_editable_flags_are_false(app):
    first = app.add_task("A", 3)
    second = app.add_task("B", 2)
    app.indent_task(second)

    rows = {r.task_id: r for r in app.projections.task_rows}
    assert rows[first].is_summary is True
    assert rows[second].is_summary is False


def test_remove_summary_task_reparents_children_to_top_level(app):
    first = app.add_task("A", 3)
    second = app.add_task("B", 2)
    app.indent_task(second)

    app.remove_task(first)

    rows = {r.task_id: r for r in app.projections.task_rows}
    assert rows[second].depth == 0
    assert rows[second].outline_number == "1"
