import mysql.connector

try:
    conn = mysql.connector.connect(
        host='127.0.0.1',
        port=3306,
        user='root',
        password='root',
        database='student_platform'
    )
    if conn.is_connected():
        print("Successfully connected to MySQL database!")
        conn.close()
except mysql.connector.Error as e:
    print(f"Error while connecting to MySQL: {e}")
