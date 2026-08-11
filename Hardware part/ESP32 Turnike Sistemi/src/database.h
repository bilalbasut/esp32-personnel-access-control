// database.h

// The #ifndef/#define lines are called "Include Guards". 
// They prevent the compiler from accidentally importing this file twice.
#ifndef DATABASE_H
#define DATABASE_H

#include <Arduino.h>

// List of authorized cards
const String authorizedCards[] = {
  "A1B2C3D4", 
  "98765432",
  "F1E2D3C4"
};

// Calculate the number of cards automatically
const int numAuthorizedCards = sizeof(authorizedCards) / sizeof(authorizedCards[0]);

#endif