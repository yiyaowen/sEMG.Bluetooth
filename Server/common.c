#include "common.h"

int fputc(int ch, FILE* f)
{
    UartTransmit((uint8_t)ch);
    return ch;
}

void InitUart(uint32_t baud_rate)
{
    uint32_t divisor;
    
    // Gating the clock.
    SIM->SCGC4 |= SIM_SCGC4_UART0_MASK;
    SIM->SCGC5 |= SIM_SCGC5_PORTA_MASK;
    
    // Configure UART clock source.
    // SOPT2: System Options Register 2
    // UART0SRC:
    //          00 Clk disabled
    //          01 MCGFLLCLK
    //          10 OSCERCLK
    //          11 MCGIRCLK
    // PLLFLLSEL:
    //           0 FLL, no divider
    //           1 PLL, divided by 2
    SIM->SOPT2 |= (SIM_SOPT2_UART0SRC(1) | SIM_SOPT2_PLLFLLSEL(0));

    // Configure Port A GPIO.
    PORTA->PCR[1] = PORT_PCR_MUX(2);
    PORTA->PCR[2] = PORT_PCR_MUX(2);
    
    // Disable UART to start configuration.
    UART0->C2 = 0;
    
    // Configure baud rate.
    // SBR: Set Baud Rate
    divisor = UART_CLOCK / (baud_rate * 16);
    UART0->BDH = UART0_BDH_SBR(divisor >> 8);
    UART0->BDL = UART0_BDL_SBR(divisor);
    
    // Configure transmit mode.
    // 8-bit data, 1-bit stop, no vefify.
    UART0->C1 = UART0->S2 = UART0->C3 = 0;
    UART0->C4 = UART0_C4_OSR(0x0F);

    // Enable UART to end configuration.
    // TE: Transmit Enable
    // RE: Receive Enable
    UART0->C2 = UART0_C2_TE_MASK | UART0_C2_RE_MASK;
}

/* UART Receive & Transmit based on Polling */

void UartTransmit(uint8_t data)
{
    // Wait util Tx data register is empty.
    while (!(UART0->S1 & 0x80))
        ;
    UART0->D = data;
}

uint8_t UartReceive(void)
{
    // Wait util Rx data register is full.
    while (!(UART0->S1 & 0x20))
        ;
    return UART0->D;
}
