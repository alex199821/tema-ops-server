-- Everyone connecting to this database sees Tbilisi time (now(), CURRENT_DATE),
-- the same as the server and the times stored in our tables.
ALTER DATABASE ops SET timezone = 'Asia/Tbilisi';