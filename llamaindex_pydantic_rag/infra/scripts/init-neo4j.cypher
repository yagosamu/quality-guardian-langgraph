// Constraints (uniqueness)
CREATE CONSTRAINT pipeline_name IF NOT EXISTS FOR (p:Pipeline) REQUIRE p.name IS UNIQUE;
CREATE CONSTRAINT table_name IF NOT EXISTS FOR (t:Table) REQUIRE t.name IS UNIQUE;
CREATE CONSTRAINT dashboard_name IF NOT EXISTS FOR (d:Dashboard) REQUIRE d.name IS UNIQUE;
CREATE CONSTRAINT team_name IF NOT EXISTS FOR (tm:Team) REQUIRE tm.name IS UNIQUE;

// Teams
CREATE (t1:Team {name: 'team-billing', slack_channel: '#billing-eng'});
CREATE (t2:Team {name: 'team-analytics', slack_channel: '#analytics'});
CREATE (t3:Team {name: 'team-platform', slack_channel: '#platform-eng'});

// Tables
CREATE (tb1:Table {name: 'customers', schema: 'public', database: 'dataops', row_count: 5000});
CREATE (tb2:Table {name: 'orders', schema: 'public', database: 'dataops', row_count: 50000});
CREATE (tb3:Table {name: 'products', schema: 'public', database: 'dataops', row_count: 200});
CREATE (tb4:Table {name: 'fact_revenue', schema: 'analytics', database: 'warehouse', row_count: 120000});
CREATE (tb5:Table {name: 'dim_customers', schema: 'analytics', database: 'warehouse', row_count: 5000});

// Pipelines
CREATE (p1:Pipeline {name: 'etl_billing_daily', schedule: '0 3 * * *', owner: 'team-billing', sla_minutes: 45});
CREATE (p2:Pipeline {name: 'etl_orders_hourly', schedule: '0 * * * *', owner: 'team-billing', sla_minutes: 15});
CREATE (p3:Pipeline {name: 'etl_customer_sync', schedule: '0 6 * * *', owner: 'team-platform', sla_minutes: 30});
CREATE (p4:Pipeline {name: 'analytics_revenue_agg', schedule: '0 5 * * *', owner: 'team-analytics', sla_minutes: 60});

// Dashboards
CREATE (d1:Dashboard {name: 'Revenue Overview', tool: 'Metabase', owner: 'team-analytics', refresh_frequency: 'hourly'});
CREATE (d2:Dashboard {name: 'Customer Health', tool: 'Metabase', owner: 'team-billing', refresh_frequency: 'daily'});
CREATE (d3:Dashboard {name: 'Pipeline Monitor', tool: 'Grafana', owner: 'team-platform', refresh_frequency: 'realtime'});

// Relationships — Pipeline reads/writes
MATCH (p:Pipeline {name: 'etl_billing_daily'}), (t:Table {name: 'orders'}) CREATE (p)-[:READS_FROM]->(t);
MATCH (p:Pipeline {name: 'etl_billing_daily'}), (t:Table {name: 'fact_revenue'}) CREATE (p)-[:WRITES_TO]->(t);
MATCH (p:Pipeline {name: 'etl_orders_hourly'}), (t:Table {name: 'orders'}) CREATE (p)-[:READS_FROM]->(t);
MATCH (p:Pipeline {name: 'etl_customer_sync'}), (t:Table {name: 'customers'}) CREATE (p)-[:READS_FROM]->(t);
MATCH (p:Pipeline {name: 'etl_customer_sync'}), (t:Table {name: 'dim_customers'}) CREATE (p)-[:WRITES_TO]->(t);
MATCH (p:Pipeline {name: 'analytics_revenue_agg'}), (t:Table {name: 'fact_revenue'}) CREATE (p)-[:READS_FROM]->(t);

// Relationships — Pipeline feeds pipeline
MATCH (p1:Pipeline {name: 'etl_billing_daily'}), (p2:Pipeline {name: 'analytics_revenue_agg'}) CREATE (p1)-[:FEEDS]->(p2);
MATCH (p1:Pipeline {name: 'etl_customer_sync'}), (p2:Pipeline {name: 'analytics_revenue_agg'}) CREATE (p1)-[:FEEDS]->(p2);

// Relationships — Table used by dashboard
MATCH (t:Table {name: 'fact_revenue'}), (d:Dashboard {name: 'Revenue Overview'}) CREATE (t)-[:USED_BY]->(d);
MATCH (t:Table {name: 'dim_customers'}), (d:Dashboard {name: 'Customer Health'}) CREATE (t)-[:USED_BY]->(d);
MATCH (t:Table {name: 'orders'}), (d:Dashboard {name: 'Pipeline Monitor'}) CREATE (t)-[:USED_BY]->(d);

// Relationships — Team owns
MATCH (tm:Team {name: 'team-billing'}), (p:Pipeline {name: 'etl_billing_daily'}) CREATE (tm)-[:OWNS]->(p);
MATCH (tm:Team {name: 'team-billing'}), (p:Pipeline {name: 'etl_orders_hourly'}) CREATE (tm)-[:OWNS]->(p);
MATCH (tm:Team {name: 'team-platform'}), (p:Pipeline {name: 'etl_customer_sync'}) CREATE (tm)-[:OWNS]->(p);
MATCH (tm:Team {name: 'team-analytics'}), (p:Pipeline {name: 'analytics_revenue_agg'}) CREATE (tm)-[:OWNS]->(p);
MATCH (tm:Team {name: 'team-billing'}), (t:Table {name: 'orders'}) CREATE (tm)-[:OWNS]->(t);
MATCH (tm:Team {name: 'team-platform'}), (t:Table {name: 'customers'}) CREATE (tm)-[:OWNS]->(t);
MATCH (tm:Team {name: 'team-analytics'}), (t:Table {name: 'fact_revenue'}) CREATE (tm)-[:OWNS]->(t);
