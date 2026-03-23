// Core node uniqueness constraints
CREATE CONSTRAINT author_key IF NOT EXISTS FOR (n:Author) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT publisher_key IF NOT EXISTS FOR (n:Publisher) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT publisher_house_key IF NOT EXISTS FOR (n:PublisherHouse) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT organization_key IF NOT EXISTS FOR (n:Organization) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT think_tank_key IF NOT EXISTS FOR (n:ThinkTank) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT topic_key IF NOT EXISTS FOR (n:Topic) REQUIRE n.key IS UNIQUE;

// Recommended properties on each node:
// name, key, bias_label, bias_score (-1..1), bias_confidence (0..1), importance_weight
//
// Relationship examples with weights:
// (:Author)-[:WRITES_FOR {weight: 0.95}]->(:Publisher)
// (:Publisher)-[:OWNED_BY {weight: 0.9}]->(:PublisherHouse)
// (:Publisher)-[:AFFILIATED_WITH {weight: 0.7}]->(:Organization)
// (:Organization)-[:ADVOCATES_FOR {weight: 0.65}]->(:Topic)
