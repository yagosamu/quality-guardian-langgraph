#!/bin/bash
# Wait for Neo4j to be ready
NEO4J_PASSWORD="${NEO4J_PASSWORD:?NEO4J_PASSWORD must be set}"

NEO4J_HOST="${NEO4J_HOST:-neo4j}"

until cypher-shell -a "bolt://${NEO4J_HOST}:7687" -u neo4j -p "$NEO4J_PASSWORD" "RETURN 1" > /dev/null 2>&1; do
    echo "Waiting for Neo4j..."
    sleep 3
done

# Run init script
cypher-shell -a "bolt://${NEO4J_HOST}:7687" -u neo4j -p "$NEO4J_PASSWORD" -f /scripts/init-neo4j.cypher
echo "Neo4j seeded successfully."
