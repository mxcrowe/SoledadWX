SELECT
  d.name,
  ROUND(d.current_level::numeric, 3) AS level,
  d.last_satisfied_heartbeat AS last_sat_hb,
  hs.heartbeat_count AS current_hb,
  CASE
    WHEN d.last_satisfied_heartbeat IS NULL THEN NULL
    ELSE GREATEST(0, hs.heartbeat_count - d.last_satisfied_heartbeat)
  END AS hb_since_sat,
  CASE d.name
    WHEN 'curiosity' THEN (SELECT value::int FROM heartbeat_config WHERE key = 'drive_curiosity_satisfaction_cooldown_heartbeats')
    WHEN 'coherence' THEN (SELECT value::int FROM heartbeat_config WHERE key = 'drive_coherence_satisfaction_cooldown_heartbeats')
    WHEN 'connection' THEN (SELECT value::int FROM heartbeat_config WHERE key = 'drive_connection_satisfaction_cooldown_heartbeats')
    WHEN 'competence' THEN (SELECT value::int FROM heartbeat_config WHERE key = 'drive_competence_satisfaction_cooldown_heartbeats')
    WHEN 'rest' THEN (SELECT value::int FROM heartbeat_config WHERE key = 'drive_rest_satisfaction_cooldown_heartbeats')
  END AS cooldown_hb
FROM drives d
CROSS JOIN heartbeat_state hs
WHERE hs.id = 1
ORDER BY d.name;