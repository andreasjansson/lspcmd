use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use fastrace::collector::{Reporter, SpanId, SpanRecord};
use leta_types::{FunctionStats, SpanNode, SpanTree};

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
    pub fn build_span_tree(&self) -> SpanTree {
        let spans = std::mem::take(&mut *self.spans.lock().unwrap());
        build_tree(spans)
    }

    pub fn collect_and_aggregate(&self) -> Vec<FunctionStats> {
        let tree = self.build_span_tree();
        tree.functions
    }
}

fn simplify_name(name: &str) -> String {
    let name = name
        .replace("::{{closure}}", "")
        .replace("leta_daemon::", "")
        .replace("leta_", "")
        .replace("handlers::", "")
        .replace("session::", "");

    if let Some(pos) = name.rfind("::") {
        name[pos + 2..].to_string()
    } else {
        name
    }
}

#[derive(Debug, Clone)]
struct RawSpan {
    span_id: SpanId,
    parent_id: SpanId,
    name: String,
    begin_ns: u64,
    duration_ns: u64,
    properties: Vec<(String, String)>,
}

fn build_tree(spans: Vec<SpanRecord>) -> SpanTree {
    if spans.is_empty() {
        return SpanTree::default();
    }

    // Debug: log all unique span names
    let unique_names: std::collections::HashSet<_> =
        spans.iter().map(|s| s.name.as_ref()).collect();
    tracing::info!(
        "build_tree: {} spans, names: {:?}",
        spans.len(),
        unique_names
    );

    let raw_spans: Vec<RawSpan> = spans
        .into_iter()
        .map(|s| RawSpan {
            span_id: s.span_id,
            parent_id: s.parent_id,
            name: simplify_name(&s.name),
            begin_ns: s.begin_time_unix_ns,
            duration_ns: s.duration_ns,
            properties: s
                .properties
                .into_iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
        })
        .collect();

    let by_id: HashMap<SpanId, &RawSpan> = raw_spans.iter().map(|s| (s.span_id, s)).collect();

    let mut children_map: HashMap<SpanId, Vec<&RawSpan>> = HashMap::new();
    let mut roots = Vec::new();

    for span in &raw_spans {
        if span.parent_id == SpanId::default() || !by_id.contains_key(&span.parent_id) {
            roots.push(span);
        } else {
            children_map.entry(span.parent_id).or_default().push(span);
        }
    }

    let total_us = roots
        .iter()
        .map(|s| s.duration_ns / 1000)
        .max()
        .unwrap_or(0);

    let root_nodes: Vec<SpanNode> = roots
        .into_iter()
        .map(|r| build_node(r, &children_map))
        .collect();

    let merged = merge_nodes(root_nodes);
    let functions = compute_function_stats(&raw_spans);

    SpanTree {
        roots: merged,
        total_us,
        functions,
    }
}

fn compute_function_stats(spans: &[RawSpan]) -> Vec<FunctionStats> {
    let mut by_name: HashMap<String, Vec<u64>> = HashMap::new();

    for span in spans {
        let duration_us = span.duration_ns / 1000;
        by_name
            .entry(span.name.clone())
            .or_default()
            .push(duration_us);
    }

    let mut stats: Vec<FunctionStats> = by_name
        .into_iter()
        .map(|(name, mut durations)| {
            durations.sort_unstable();
            let calls = durations.len() as u32;
            let total_us: u64 = durations.iter().sum();
            let avg_us = if calls > 0 {
                total_us / calls as u64
            } else {
                0
            };
            let p90_idx = ((durations.len() as f64 * 0.9).ceil() as usize).saturating_sub(1);
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

fn build_node(span: &RawSpan, children_map: &HashMap<SpanId, Vec<&RawSpan>>) -> SpanNode {
    let total_us = span.duration_ns / 1000;

    let raw_children: Vec<SpanNode> = children_map
        .get(&span.span_id)
        .map(|kids| kids.iter().map(|c| build_node(c, children_map)).collect())
        .unwrap_or_default();

    let is_parallel = detect_parallel(children_map.get(&span.span_id).unwrap_or(&vec![]));

    let children_time: u64 = if is_parallel {
        raw_children.iter().map(|c| c.total_us).max().unwrap_or(0)
    } else {
        raw_children.iter().map(|c| c.total_us).sum()
    };

    let self_us = total_us.saturating_sub(children_time);

    let children = merge_nodes(raw_children);

    SpanNode {
        name: span.name.clone(),
        self_us,
        total_us,
        calls: 1,
        children,
        is_parallel,
        properties: span.properties.clone(),
    }
}

fn detect_parallel(spans: &[&RawSpan]) -> bool {
    if spans.len() < 2 {
        return false;
    }

    let mut sorted: Vec<_> = spans.iter().collect();
    sorted.sort_by_key(|s| s.begin_ns);

    for i in 1..sorted.len() {
        let prev_end = sorted[i - 1].begin_ns + sorted[i - 1].duration_ns;
        if sorted[i].begin_ns < prev_end {
            return true;
        }
    }
    false
}

fn merge_nodes(nodes: Vec<SpanNode>) -> Vec<SpanNode> {
    let mut by_name: HashMap<String, Vec<SpanNode>> = HashMap::new();

    for node in nodes {
        by_name.entry(node.name.clone()).or_default().push(node);
    }

    let mut merged: Vec<SpanNode> = by_name
        .into_iter()
        .map(|(name, nodes)| {
            let calls = nodes.len() as u32;
            let total_us: u64 = nodes.iter().map(|n| n.total_us).sum();
            let self_us: u64 = nodes.iter().map(|n| n.self_us).sum();
            let is_parallel = nodes.iter().any(|n| n.is_parallel);

            // Collect all properties from all nodes
            let properties: Vec<(String, String)> =
                nodes.iter().flat_map(|n| n.properties.clone()).collect();

            let all_children: Vec<SpanNode> = nodes.into_iter().flat_map(|n| n.children).collect();
            let children = merge_nodes(all_children);

            SpanNode {
                name,
                self_us,
                total_us,
                calls,
                children,
                is_parallel,
                properties,
            }
        })
        .collect();

    merged.sort_by(|a, b| b.total_us.cmp(&a.total_us));
    merged
}
