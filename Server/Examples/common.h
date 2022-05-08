#ifndef SEMG_SERVER_EXAMPLES_COMMON_H
#define SEMG_SERVER_EXAMPLES_COMMON_H

#include <stdio.h>

#include <MKL25Z4.h>

#include <FreeRTOS.h>
#include <task.h>

// UART

#define UART_CLOCK DEFAULT_SYSTEM_CLOCK

int fputc(int ch, FILE* f);

void InitUart(uint32_t baud_rate);

void UartTransmit(uint8_t data);

uint8_t UartReceive(void);

#endif // SEMG_SERVER_EXAMPLES_COMMON_H
