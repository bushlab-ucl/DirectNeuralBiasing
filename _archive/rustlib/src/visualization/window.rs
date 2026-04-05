// src/rustlib/src/visualization/window.rs

use super::plotter::SharedPlotter;
use super::VisualizationConfig;
use eframe::egui;

pub struct VisualizationWindow {
    plotter: SharedPlotter,
    config: VisualizationConfig,
}

impl VisualizationWindow {
    pub fn new(plotter: SharedPlotter, config: VisualizationConfig) -> Self {
        Self { plotter, config }
    }

    pub fn run(plotter: SharedPlotter, config: VisualizationConfig) -> Result<(), eframe::Error> {
        let options = eframe::NativeOptions {
            viewport: egui::ViewportBuilder::default()
                .with_inner_size([config.window_width as f32, config.window_height as f32])
                .with_title("DirectNeuralBiasing - Real-Time Visualization"),
            ..Default::default()
        };

        eframe::run_native(
            "DirectNeuralBiasing Visualization",
            options,
            Box::new(|_cc| Ok(Box::new(VisualizationWindow::new(plotter, config)))),
        )
    }
}

impl eframe::App for VisualizationWindow {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // Request continuous repainting for real-time updates
        ctx.request_repaint();

        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading("DirectNeuralBiasing - Real-Time Signal Visualization");
            ui.separator();

            // Lock the plotter to access data
            let plotter = self.plotter.lock().unwrap();
            let time_range = plotter.get_time_range();

            if time_range.is_none() {
                ui.label("Waiting for data...");
                return;
            }

            let (min_time, max_time) = time_range.unwrap();

            egui::ScrollArea::vertical().show(ui, |ui| {
                // Plot raw signal
                if self.config.show_raw_signal {
                    ui.heading("Raw Signal");
                    self.plot_signal(
                        ui,
                        "raw_signal",
                        &plotter.get_raw_buffer(),
                        min_time,
                        max_time,
                        egui::Color32::LIGHT_BLUE,
                    );
                    ui.add_space(10.0);
                }

                // Plot filtered signals
                if self.config.show_filtered_signals {
                    let filtered_buffers = plotter.get_all_filtered_buffers();

                    for (filter_id, buffer) in filtered_buffers.iter() {
                        ui.heading(format!("Filtered Signal: {}", filter_id));
                        self.plot_signal(
                            ui,
                            filter_id,
                            buffer,
                            min_time,
                            max_time,
                            egui::Color32::LIGHT_GREEN,
                        );
                        ui.add_space(10.0);
                    }
                }

                // Show detection statistics
                if self.config.show_detections {
                    ui.separator();
                    ui.heading("Detections");

                    let markers = plotter.get_detection_markers();
                    let mut detection_counts: std::collections::HashMap<String, usize> =
                        std::collections::HashMap::new();

                    for (_, detector_id, active) in markers.iter() {
                        if *active {
                            *detection_counts.entry(detector_id.clone()).or_insert(0) += 1;
                        }
                    }

                    ui.horizontal(|ui| {
                        for (detector_id, count) in detection_counts.iter() {
                            ui.label(format!("{}: {} events", detector_id, count));
                            ui.separator();
                        }
                    });
                }
            });
        });
    }
}

impl VisualizationWindow {
    fn plot_signal(
        &self,
        ui: &mut egui::Ui,
        name: &str,
        data: &[(f64, f64)],
        min_time: f64,
        max_time: f64,
        color: egui::Color32,
    ) {
        // Import from egui_plot crate, not egui::plot
        use egui_plot::{Line, Plot, PlotPoints, VLine};

        if data.is_empty() {
            return;
        }

        let plot_height = self.config.plot_height_per_signal as f32;

        // Convert data to PlotPoints
        let points: PlotPoints = data.iter().map(|(t, v)| [*t, *v]).collect();

        let line = Line::new(points).color(color).width(1.5);

        // Get detection markers within the time range
        let plotter = self.plotter.lock().unwrap();
        let markers = plotter.get_detection_markers();
        let mut vlines = Vec::new();

        for (timestamp, detector_id, active) in markers.iter() {
            if *active && *timestamp >= min_time && *timestamp <= max_time {
                vlines.push(
                    VLine::new(*timestamp)
                        .color(egui::Color32::RED)
                        .width(2.0)
                        .name(detector_id),
                );
            }
        }

        Plot::new(name)
            .height(plot_height)
            .show_axes([true, true])
            .show_grid([true, true])
            .allow_zoom(true)
            .allow_drag(true)
            .allow_scroll(true)
            .show(ui, |plot_ui| {
                plot_ui.line(line);

                // Add detection markers as vertical lines
                for vline in vlines {
                    plot_ui.vline(vline);
                }
            });
    }
}

/// Spawns the visualization window in a separate thread
/// This is the function that needs to be exported and used in signal_processor.rs
pub fn spawn_visualization_window(
    plotter: SharedPlotter,
    config: VisualizationConfig,
) -> std::thread::JoinHandle<()> {
    std::thread::spawn(move || {
        if let Err(e) = VisualizationWindow::run(plotter, config) {
            eprintln!("Visualization window error: {}", e);
        }
    })
}
