"""Framework-free Plotly figure builders.

Each function takes plain data (arrays, dicts, numbers) produced by ``core`` and
returns a ``plotly.graph_objects.Figure``; ``fig.to_dict()`` / ``fig.to_json()``
feeds ``react-plotly.js`` directly, and the PDF reports render the same figure.
"""
