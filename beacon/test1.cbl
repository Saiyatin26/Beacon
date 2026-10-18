       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC X(5) VALUE 'PF3'.
       01 B PIC X(5) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE TRUE
               WHEN A = 'PF3'
                   MOVE 'PF3' TO B
               WHEN A = 'PF5'
                   MOVE 'PF5' TO B
               WHEN OTHER
                   MOVE 'ENT' TO B
           END-EVALUATE
           DISPLAY 'B IS: ' B
           STOP RUN.
