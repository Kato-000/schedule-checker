// リリース版ではコンソール窓を出さない
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    schedule_checker_lib::run()
}
