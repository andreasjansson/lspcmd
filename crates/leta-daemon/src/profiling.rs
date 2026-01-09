use std::collections::HashMap;
use std::future::Future;
use std::sync::{Arc, Mutex};

use fastrace::collector::{Config as FastraceConfig, Reporter, SpanRecord};
use fastrace::prelude::*;
use leta_types::FunctionStats;

pub struct CollectingReporter {
    spans: Arc<Mutex<Vec<SpanRecord>>>,
}

impl CollectingReporter {
    pub fn new() -> (Self, SpanCollector) {
        let spans = Arc::new(Mutex::new(Vec::new()));
        (
            Self {
                spans: spans.clone(),
            },
            SpanCollector { spans },
        )
    }
}

impl Reporter for CollectingReporter {
    fn report(&mut self, spans: Vec<SpanRecord>) {
        self.spans.lock().unwrap().extend(spans);
    }
}

pub struct SpanCollector {
    spans: Arc<Mutex<Vec<SpanRecord>>>,
}

impl SpanCollector {
    pub fn collect_and_aggregate(&self) -> Vec<FunctionStats> {
        let spans = std::mem::take(&mut *self.spans.lock().unwrap());
        aggregate_spans(spans)
    }
}

fn aggregate_spans(spans: Vec<SpanRecord>) -> Vec<FunctionStats> {
    let mut by_name: HashMap<String, Vec<u64>> = HashMap::new();

    for span in spans {
        let duration_us = span.duration_ns / 1000;
        by_name
            .entry(span.name.to_string())
            .or_default()
            .push(duration_us);
    }

    let mut stats: Vec<FunctionStats> = by_name
        .into_iter()
        .map(|(name, mut durations)| {
            durations.sort_unstable();
            let calls = durations.len() as u32;
            let total_us: u64 = durations.iter().sum();
            let avg_us = total_us / calls as u64;
            let p90_idx = (durations.len() as f64 * 0.9) as usize;
            let p90_us = durations.get(p90_idx).copied().unwrap_or(0);
            let max_us = durations.last().copied().unwrap_or(0);

            FunctionStats {
                name,
                calls,
                total_us,
                avg_us,
                p90_us,
                max_us,
            }
        })
        .collect();

    stats.sort_by(|a, b| b.total_us.cmp(&a.total_us));
    stats
}
