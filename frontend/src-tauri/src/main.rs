// Cache la console Windows en release (mode dev affiche les logs normalement)
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    hermes_lib::run()
}
