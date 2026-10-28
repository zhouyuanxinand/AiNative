"""Approved taskbook and published project-plan scenarios."""
from tests.support.rd_project import REVIEWER, command
from tests.support.taskbook_release import planned, submit


def approved(store):
    d=submit(store,planned(store))
    return command(store,d,'decide_review',{'review_id':d['reviews'][-1]['id'],'decision':'approved'},REVIEWER)


def published(store):
    d=approved(store)
    return command(store,d,'publish_plan',{'task_id':d['tasks'][0]['id'],'release_id':d['taskbook_releases'][0]['id']})
