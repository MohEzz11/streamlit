/*
  Run ONCE in SQL Server Management Studio (as an administrator) before
  starting Heygen Passport in Docker. It creates the separate Heygen database
  and a dedicated SQL login that can only use that database.

  1. Replace CHANGE_ME_Strong#Passw0rd with a strong password of your own.
  2. Put the same login and password in heygen_passport\local.env.
  Nothing here touches any other database.
*/
IF DB_ID(N'HeygenPassport') IS NULL
    CREATE DATABASE [HeygenPassport];
GO
IF SUSER_ID(N'heygen_app') IS NULL
    CREATE LOGIN [heygen_app] WITH PASSWORD = N'CHANGE_ME_Strong#Passw0rd',
        DEFAULT_DATABASE = [HeygenPassport], CHECK_POLICY = ON;
GO
USE [HeygenPassport];
GO
IF USER_ID(N'heygen_app') IS NULL
    CREATE USER [heygen_app] FOR LOGIN [heygen_app];
ALTER ROLE db_owner ADD MEMBER [heygen_app];
GO
