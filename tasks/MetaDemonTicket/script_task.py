from module.exception import TaskEnd
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
from tasks.MetaDemonTicket.ticket_farming import run_ticket_farming


class ScriptTask(GameUi):
    def run(self):
        scheduler = self.config.meta_demon_ticket.scheduler
        if scheduler.waiting_for_realm_raid:
            with self.config.lock_config:
                scheduler.waiting_for_realm_raid = False
                self.config.save()
        mode = self.config.meta_demon_ticket.general_config.mode
        full = run_ticket_farming(self, mode)
        self.set_next_run(task='MetaDemonTicket', success=full)
        self.goto_page(page_main)
        raise TaskEnd
