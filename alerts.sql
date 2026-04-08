CREATE DATABASE personal_safety; 

USE personal_safety;

DROP TABLE IF EXISTS alerts;

CREATE TABLE alerts (
    id INT PRIMARY KEY,
    message VARCHAR(255),
    latitude FLOAT,
    longitude FLOAT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
sp_help alerts;


DROP TABLE IF EXISTS users;
CREATE TABLE users (
    id INT PRIMARY KEY,
    name VARCHAR(25),
    email VARCHAR(25),
    password VARCHAR(25)
);

sp_help users;



DROP TABLE IF EXISTS locations;
CREATE TABLE locations (
    id INT PRIMARY KEY,
    user_id INT,
    latitude FLOAT,
    longitude FLOAT,
    timestamp DATETIME,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
sp_help locations;



DROP TABLE IF EXISTS contacts;
CREATE TABLE contacts (
    id INT PRIMARY KEY,
    user_id INT,
    contact_name VARCHAR(25),
    contact_number VARCHAR(15),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
sp_help contacts;





